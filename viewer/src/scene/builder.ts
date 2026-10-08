// Builds one vertex coloured geometry out of rounded boxes. Used for the agent and the creatures.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

type Part = { geom: THREE.BufferGeometry };

export class Builder {
  parts: Part[] = [];
  private col = new THREE.Color();

  /** A rounded box centred at (x, y, z). y is measured from the creature's feet. */
  add(x: number, y: number, z: number, w: number, h: number, d: number, color: number, radius = 0.06, rounded = true): this {
    const src = rounded
      ? new RoundedBoxGeometry(w, h, d, 2, Math.min(radius, Math.min(w, h, d) / 2.2))
      : new THREE.BoxGeometry(w, h, d);
    // RoundedBoxGeometry is already non-indexed; calling toNonIndexed on it logs a warning.
    const g = src.index ? src.toNonIndexed() : src;
    if (g !== src) src.dispose();
    g.deleteAttribute("uv");
    const n = g.getAttribute("position").count;
    const colors = new Float32Array(n * 3);
    this.col.setHex(color);
    for (let i = 0; i < n; i++) { colors[i * 3] = this.col.r; colors[i * 3 + 1] = this.col.g; colors[i * 3 + 2] = this.col.b; }
    g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    g.translate(x, y, z);
    this.parts.push({ geom: g });
    return this;
  }

  build(): THREE.BufferGeometry {
    const merged = mergeGeometries(this.parts.map((p) => p.geom), false);
    for (const p of this.parts) p.geom.dispose();
    merged.computeBoundingSphere();
    return merged;
  }
}

/**
 * A flat, see-through colour drawn only where the mesh is hidden behind something (GreaterDepth),
 * so a character inside a tunnel or behind a hill still shows as a silhouette. Front faces only
 * and no depth writes, so the visible parts of the character are not tinted.
 */
export function xrayMaterial(color: number, opacity = 0.5): THREE.MeshBasicMaterial {
  return new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false,
    depthFunc: THREE.GreaterDepth, fog: false });
}
