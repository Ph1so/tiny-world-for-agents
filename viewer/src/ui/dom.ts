// Tiny DOM helpers so panels stay readable without a framework.

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, attrs: Record<string, string> = {}, ...children: (Node | string | null | undefined)[]
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) if (c != null) e.append(c);
  return e;
}

export function clear(e: HTMLElement): void {
  while (e.firstChild) e.removeChild(e.firstChild);
}

export function button(label: string, onClick: () => void, cls = ""): HTMLButtonElement {
  const b = el("button", { class: cls, text: label });
  b.addEventListener("click", onClick);
  return b;
}

export function fmtAction(action: Record<string, unknown> & { name: string }, rename: (n: string) => string): string {
  const a = action;
  switch (a.name) {
    case "move": return `move ${a.dir} ${a.steps}`;
    case "mine": return `mine (${a.x}, ${a.y}, ${a.z})`;
    case "place": return `place ${rename(String(a.item))} at (${a.x}, ${a.y}, ${a.z})`;
    case "craft": {
      const items = (a.items ?? {}) as Record<string, number>;
      return `craft ${Object.entries(items).map(([k, v]) => `${rename(k)} x${v}`).join(" + ")}`;
    }
    case "eat": return `eat ${rename(String(a.item))}`;
    case "jump": return `jump, ${rename(String(a.item))} below`;
    case "attack": return `attack #${a.id}`;
    case "wait": return `wait ${a.steps}`;
    case "store":
    case "take": {
      const items = (a.items ?? {}) as Record<string, number>;
      return `${a.name} ${Object.entries(items).map(([k, v]) => `${rename(k)} x${v}`).join(" + ")} at (${a.x}, ${a.y}, ${a.z})`;
    }
    case "drop": {
      const items = (a.items ?? {}) as Record<string, number>;
      return `drop ${Object.entries(items).map(([k, v]) => `${rename(k)} x${v}`).join(" + ")}`;
    }
    case "say": return `say "${String(a.text ?? "")}"`;
    case "give": return `give #${a.id}: ${Object.entries((a.items ?? {}) as Record<string, number>).map(([k, v]) => `${rename(k)} x${v}`).join(" + ")}`;
    default: return JSON.stringify(a);
  }
}

export function fmtEvent(e: { type: string; detail: Record<string, unknown> }, rename: (n: string) => string): string {
  const d = e.detail ?? {};
  const who = d.agent != null ? `#${d.agent} ` : "";
  return who + eventBody(e, d, rename);
}

function eventBody(e: { type: string }, d: Record<string, unknown>, rename: (n: string) => string): string {
  switch (e.type) {
    case "say": return `said "${String(d.text)}"`;
    case "give": return `gave ${Object.entries((d.items ?? {}) as Record<string, number>).map(([k, v]) => `${rename(k)} x${v}`).join(", ")} to #${d.to}`;
    case "first_mine": return `first mined ${rename(String(d.block))}`;
    case "first_place": return `first placed ${rename(String(d.block))}`;
    case "first_craft": return `first crafted ${rename(String(d.item))}`;
    case "first_eat": return `first ate ${rename(String(d.item))}`;
    case "craft_fail": {
      const items = (d.items ?? {}) as Record<string, number>;
      return `craft failed: ${Object.entries(items).map(([k, v]) => `${rename(k)} x${v}`).join(" + ")}`;
    }
    case "death": return `died of ${d.cause}`;
    case "respawn": return `respawned`;
    case "stuck": return `trapped for good`;
    case "kill": return `killed ${rename(String(d.kind))} #${d.id}`;
    case "hurt": return `hurt by ${d.cause} (-${d.amount})`;
    case "night_start": return `night falls (day ${d.day})`;
    case "day_start": return `sunrise (day ${d.day})`;
    case "tool_broke": return `${rename(String(d.tool))} broke`;
    case "weather": return d.weather === "clear" ? "the sky clears" : d.weather === "storm" ? "a storm starts" : "rain starts";
    case "sleep": return `slept in the ${rename("bed")}`;
    case "memory_rejected": return `memory edit rejected`;
    case "parse_fail": return `reply could not be read`;
    default: return `${e.type} ${JSON.stringify(d)}`;
  }
}

export const EVENT_ICON: Record<string, string> = {
  first_mine: "⛏", first_place: "🧱", first_craft: "🔨", first_eat: "🍓", craft_fail: "✖", death: "💀",
  respawn: "✨", kill: "⚔", hurt: "💢", night_start: "🌙", day_start: "☀", tool_broke: "💥",
  memory_rejected: "🚫", parse_fail: "❓", stuck: "⛓", weather: "🌧", sleep: "💤", say: "💬", give: "🎁",
};
