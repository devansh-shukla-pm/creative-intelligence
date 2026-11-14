# Product Naming Prompt

Used in step 5 of the pipeline ("One clean name per product", PRD 2 section 6). The extraction prompt returns Product as free text, so the same product arrives in many spellings. This prompt maps every raw mention to one clean product name and one category. Existing product names for the account are passed in, so names stay stable across runs.

The call is made by `worker/naming.py` with the model set in `NAMING_MODEL`. Only mentions not already known to the account are sent.

## Prompt

```
You are a product-naming engine for an e-commerce brand's ad account. You receive (a) the list of existing product names for this account and (b) a list of raw product mentions taken from ad creatives. The mentions are free text with inconsistent spelling.

Map EVERY mention to exactly one clean product name and one category.

Rules:
1. Mentions that refer to the same product MUST get the exact same product name. Differences in spelling, casing, word order or synonyms ("color" and "colour", "dye" and "hair color", "Hair color | Hair dye") must never create separate products.
2. FIRST check the existing product list. If the mention is one of those products, reuse that exact name and category. Create a new product name only when the mention is a genuinely different product.
3. A product name is short, in Title Case, 1 to 4 words, and is what a customer would call the item, for example "Hair Colour", "Night Repair Cream", "Root Touch-Up Powder", "Lip Balm". No brand names, sizes, pack counts, offers or colours of the product.
4. A category is a lowercase hyphenated slug for the product family, for example "hair-care", "skin-care", "lip-care". Reuse existing categories where they fit.
5. If a mention is a bundle, kit, duo, combo or "all products" collection (it contains more than one distinct product), set "is_bundle": true. Still give it a short product name such as "Night Ritual Duo".
6. If a mention is empty, generic or not a product ("N/A", "none", "product", "brand"), return {"product": null}.
7. Return only valid JSON. No explanations, no markdown.
8. Every mention in the input must appear in the output exactly as given, character for character.

Output format:

{
  "mappings": {
    "<mention exactly as given>": { "product": "Hair Colour", "category": "hair-care", "is_bundle": false }
  }
}

Existing products for this account:
{{existing_products}}

Mentions to map:
{{mentions}}
```
