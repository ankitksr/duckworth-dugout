/**
 * Convert an array of [x, y] points into a smooth SVG <path> `d` attribute
 * using Catmull-Rom to cubic bezier conversion.
 *
 * The resulting curve passes through every input point exactly (interpolating,
 * not approximating) and has smooth C1-continuous tangents at each point.
 *
 * @param points  Array of [x, y] coordinate pairs
 * @param tension Catmull-Rom tension (0 = Catmull-Rom default, 1 = straight lines)
 *                Default 0 gives a visually smooth curve.
 * @returns       SVG path `d` attribute string, or empty string if < 2 points
 */
export function pointsToSmoothPath(
  points: [number, number][],
  tension = 0,
): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M${points[0][0]},${points[0][1]}`;
  if (points.length === 2) {
    return `M${points[0][0]},${points[0][1]}L${points[1][0]},${points[1][1]}`;
  }

  const alpha = 1 - tension; // scale factor for tangent vectors

  const segments: string[] = [`M${points[0][0]},${points[0][1]}`];

  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i === 0 ? 0 : i - 1];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2 < points.length ? i + 2 : points.length - 1];

    // Catmull-Rom tangents scaled by alpha / 6 for cubic bezier control points
    // The 1/6 factor converts from Catmull-Rom to cubic bezier parameterization
    const cp1x = p1[0] + (alpha * (p2[0] - p0[0])) / 6;
    const cp1y = p1[1] + (alpha * (p2[1] - p0[1])) / 6;
    const cp2x = p2[0] - (alpha * (p3[0] - p1[0])) / 6;
    const cp2y = p2[1] - (alpha * (p3[1] - p1[1])) / 6;

    segments.push(`C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2[0]},${p2[1]}`);
  }

  return segments.join("");
}
