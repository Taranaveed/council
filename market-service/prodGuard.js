/** Production startup guards for market-service. */

export const MARKET_SECRET_MIN_LEN = 24;

export function isProductionLike(env = process.env) {
  return (
    Boolean(env.RENDER) ||
    ["production", "prod"].includes(String(env.ENV || "").toLowerCase()) ||
    String(env.NODE_ENV || "").toLowerCase() === "production"
  );
}

/**
 * @returns {{ ok: true } | { ok: false, message: string }}
 */
export function checkMarketServiceSecret(env = process.env) {
  if (!isProductionLike(env)) return { ok: true };
  const secret = String(env.MARKET_SERVICE_SECRET || "").trim();
  if (!secret || secret.length < MARKET_SECRET_MIN_LEN) {
    return {
      ok: false,
      message:
        `[auth] MARKET_SERVICE_SECRET must be set to a shared secret of at least ${MARKET_SECRET_MIN_LEN} characters in production ` +
        "(same value on API and market-service). Refusing to start.",
    };
  }
  return { ok: true };
}

export function assertMarketSecretOrExit(env = process.env, exitFn = process.exit) {
  const result = checkMarketServiceSecret(env);
  if (!result.ok) {
    console.error(result.message);
    exitFn(1);
  }
}
