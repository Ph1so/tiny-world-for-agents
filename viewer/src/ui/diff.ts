// Line diff with a word diff inside changed line pairs. Small inputs (memory files are a few
// thousand characters), so a plain LCS table is fine.

export type Span = { kind: "same" | "add" | "del"; text: string };
export type DiffLine = { kind: "same" | "add" | "del"; spans: Span[] };

function lcsDiff<T>(a: T[], b: T[], eq: (x: T, y: T) => boolean): { kind: "same" | "add" | "del"; item: T }[] {
  const n = a.length, m = b.length;
  // Cap the table so a huge rewrite does not freeze the page.
  if (n * m > 4_000_000) {
    return [...a.map((item) => ({ kind: "del" as const, item })), ...b.map((item) => ({ kind: "add" as const, item }))];
  }
  const dp = new Uint32Array((n + 1) * (m + 1));
  const w = m + 1;
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] = eq(a[i], b[j]) ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
    }
  }
  const out: { kind: "same" | "add" | "del"; item: T }[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (eq(a[i], b[j])) { out.push({ kind: "same", item: a[i] }); i++; j++; }
    else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) { out.push({ kind: "del", item: a[i] }); i++; }
    else { out.push({ kind: "add", item: b[j] }); j++; }
  }
  while (i < n) out.push({ kind: "del", item: a[i++] });
  while (j < m) out.push({ kind: "add", item: b[j++] });
  return out;
}

function words(s: string): string[] {
  return s.match(/\s+|[^\s]+/g) ?? [];
}

/** Word level spans for one old/new line pair. */
export function wordDiff(oldLine: string, newLine: string): { del: Span[]; add: Span[] } {
  const d = lcsDiff(words(oldLine), words(newLine), (x, y) => x === y);
  const del: Span[] = [], add: Span[] = [];
  for (const e of d) {
    if (e.kind === "same") { del.push({ kind: "same", text: e.item }); add.push({ kind: "same", text: e.item }); }
    else if (e.kind === "del") del.push({ kind: "del", text: e.item });
    else add.push({ kind: "add", text: e.item });
  }
  return { del, add };
}

/** Line diff. A deleted line directly followed by an added one is shown with word level marks. */
export function lineDiff(oldText: string, newText: string): DiffLine[] {
  const a = oldText.length ? oldText.split("\n") : [];
  const b = newText.length ? newText.split("\n") : [];
  const d = lcsDiff(a, b, (x, y) => x === y);
  const out: DiffLine[] = [];
  let k = 0;
  while (k < d.length) {
    const e = d[k];
    if (e.kind === "same") { out.push({ kind: "same", spans: [{ kind: "same", text: e.item }] }); k++; continue; }
    // Collect a run of dels then adds and pair them up.
    const dels: string[] = [], adds: string[] = [];
    while (k < d.length && d[k].kind === "del") dels.push(d[k++].item);
    while (k < d.length && d[k].kind === "add") adds.push(d[k++].item);
    const pairs = Math.min(dels.length, adds.length);
    for (let p = 0; p < pairs; p++) {
      const wd = wordDiff(dels[p], adds[p]);
      out.push({ kind: "del", spans: wd.del });
      out.push({ kind: "add", spans: wd.add });
    }
    for (let p = pairs; p < dels.length; p++) out.push({ kind: "del", spans: [{ kind: "del", text: dels[p] }] });
    for (let p = pairs; p < adds.length; p++) out.push({ kind: "add", spans: [{ kind: "add", text: adds[p] }] });
  }
  return out;
}

export function hasChanges(lines: DiffLine[]): boolean {
  return lines.some((l) => l.kind !== "same");
}
