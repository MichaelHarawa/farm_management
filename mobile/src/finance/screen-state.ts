/** Render-time guard. Identity equality, not a label/UUID match or a delayed effect. */
export function visibleFinancialPage<T extends { owner: object }>(page: T | null, session: object | null, unlocked: boolean): T | null {
  return session !== null && unlocked && page?.owner === session ? page : null;
}
