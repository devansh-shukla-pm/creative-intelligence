"""Step: extraction prompt on every ad that is not already cached.

Ported from the creative extraction dashboard (extractAd): a video ad is sent as a video url and falls back to its
thumbnail if the model cannot read the video; a carousel sends every slide; an image sends the image.
"""
from __future__ import annotations
import concurrent.futures as cf
from . import cache, config
from .llm import LLMError
from .prompts import extraction_prompt

DONE = ("ok", "fallback", "skipped", "failed")

def _image_parts(urls):
    return [{"type": "image_url", "image_url": {"url": u}} for u in urls if u]

def _copy_part(c):
    """Meta's own ad copy and CTA button, sent as extra context. For video we cannot watch it is the best evidence of the pitch."""
    cp = c.get("copy") or {}
    if not cp: return []
    lines = [f"- {label}: {cp[k]}" for k, label in (("primary_text", "Primary text"), ("headline", "Headline"),
                                                    ("description", "Description"), ("cta_button", "CTA button")) if cp.get(k)]
    note = ("\n\nMETA AD COPY (set in Ads Manager, not necessarily shown on screen):\n" + "\n".join(lines) +
            "\nUse it as supporting evidence. If the closing call to action is not visible in the creative, use the CTA button as cta_text. "
            "Never copy it into a field the creative itself does not support.")
    return [{"type": "text", "text": note}]

def extract_one(llm, ad, video_url=None, frames=None):
    """-> (extraction dict, used_fallback). Raises if there is nothing usable to send or the model keeps failing."""
    c = ad["creative"]
    prompt = [{"type": "text", "text": extraction_prompt()}] + _copy_part(c)
    is_video = c.get("media_type") == "VIDEO"
    fallback = False

    if is_video and video_url:
        try:
            return llm.chat_json(config.EXTRACTION_MODEL, prompt + [{"type": "video_url", "video_url": {"url": video_url}}],
                                 max_tokens=6000, label="extraction"), False
        except LLMError:
            fallback = True                      # model could not read the video: try the thumbnail
    elif is_video:
        fallback = True                          # no video url available at all

    if c.get("media_type") == "CAROUSEL" and c.get("carousel_urls"):
        return llm.chat_json(config.EXTRACTION_MODEL, prompt + _image_parts(c["carousel_urls"]), max_tokens=6000, label="extraction"), False

    if is_video and frames:                      # several frames, including the end card, beat one thumbnail
        return llm.chat_json(config.EXTRACTION_MODEL, prompt + _image_parts(frames), max_tokens=6000, label="extraction"), True

    image = c.get("thumbnail_url") if is_video else (c.get("image_url") or c.get("thumbnail_url"))
    image = image or c.get("thumbnail_url") or c.get("image_url")
    if not image:
        raise LLMError("No creative image or video available")
    out = llm.chat_json(config.EXTRACTION_MODEL, prompt + _image_parts([image]), max_tokens=6000, label="extraction")
    return out, fallback

def needs_extraction(row):
    if row is None: return True
    if row.get("extraction_status") in DONE: return False
    return True

def run_extraction(conn, rep, llm, source, ads, cached, progress):
    """Extract every ad that has no result yet. Writes each result to the cache the moment it arrives."""
    todo = [a for a in ads if needs_extraction(cached.get(a["ad_id"]))]
    total_ads = len(ads)
    already = total_ads - len(todo)
    if not todo:
        progress(f"All {total_ads} ads already classified (cache)", total_ads, total_ads)
        return {"new": 0, "ok": 0, "failed": 0}

    vids = [a for a in todo if a["creative"].get("media_type") == "VIDEO"]
    video_urls = source.video_urls(vids) if vids else {}
    frames = source.video_frames([a for a in vids if a["ad_id"] not in video_urls]) if vids else {}
    done = already; ok = failed = 0
    progress(f"Reading {len(todo)} new ads ({already} already cached)", done, total_ads)

    def work(ad):
        return extract_one(llm, ad, video_urls.get(ad["ad_id"]), frames.get(ad["ad_id"]))

    workers = config.EXTRACT_CONCURRENCY or 12 * getattr(llm, "n_keys", 1)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(work, a): a for a in todo}
        try:
            for fut in cf.as_completed(futs):
                ad = futs[fut]
                prev = cached.get(ad["ad_id"]) or {}
                attempts = (prev.get("extraction_attempts") or 0) + 1
                try:
                    result, fb = fut.result()
                    if not isinstance(result, dict):
                        raise LLMError("extraction did not return an object")
                    cache.save_extraction(conn, rep.account_id, ad["ad_id"], result, "fallback" if fb else "ok", attempts)
                    ok += 1
                except Exception as e:                       # one bad ad must never block the report
                    no_media = "No creative" in str(e)
                    final = no_media or attempts >= config.EXTRACT_ATTEMPTS
                    cache.bump_attempt(conn, rep.account_id, ad["ad_id"], attempts, ("skipped" if no_media else "failed") if final else None)
                    failed += 1
                done += 1
                progress(f"Reading ads: {done} of {total_ads}", done, total_ads)
        except BaseException:
            for f in futs: f.cancel()        # Cancel pressed or a hard failure: do not start the reads still queued
            raise
    return {"new": len(todo), "ok": ok, "failed": failed}
