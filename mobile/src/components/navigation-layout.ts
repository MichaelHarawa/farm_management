// Keep all five destinations visible. Enlarged text reflows instead of being
// shrunk/capped or forcing labels into a fixed-height, five-column tab bar.
export function navigationColumns(width: number, fontScale: number): 2 | 3 | 5 {
  const scale = Number.isFinite(fontScale) && fontScale > 0 ? fontScale : 1;
  const available = Number.isFinite(width) && width > 0 ? width : 320;
  const minimumItemWidth = 64 * Math.max(1, scale);
  if (available >= minimumItemWidth * 5) return 5;
  if (available >= minimumItemWidth * 3) return 3;
  return 2;
}
