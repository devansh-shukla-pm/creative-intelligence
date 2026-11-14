import pg from 'pg';
import { config } from './config.js';

// One small pool per function instance. Neon's pooled connection string is expected in production.
let pool;
function getPool() {
  if (!pool) {
    if (!config.databaseUrl) throw new Error('DATABASE_URL is not set');
    pool = new pg.Pool({
      connectionString: config.databaseUrl,
      max: config.isProd ? 1 : 4,
      idleTimeoutMillis: 10_000,
      // SSL comes from the connection string (Neon URLs carry ?sslmode=require); local sockets need none.
    });
  }
  return pool;
}

let migrated = false;
export async function q(text, params = []) {
  try {
    const r = await getPool().query(text, params);
    return r.rows;
  } catch (e) {
    // A fresh database has no tables yet: create them once, then retry.
    if (e.code === '42P01' && !migrated) { migrated = true; await migrate(); return (await getPool().query(text, params)).rows; }
    throw e;
  }
}
export async function one(text, params = []) {
  const rows = await q(text, params);
  return rows[0] || null;
}
export async function closeDb() { if (pool) { await pool.end(); pool = undefined; } }

// Apply db/schema.sql (idempotent). Used by dev server, tests and the worker bootstrap.
export async function migrate() {
  const { readFile } = await import('node:fs/promises');
  const sql = await readFile(new URL('../db/schema.sql', import.meta.url), 'utf8');
  await getPool().query(sql);
}
