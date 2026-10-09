// Block colours. Soft pastels, one base colour per block; faces are shaded by direction and
// jittered a little per cell so big flat areas do not look like plastic.

export const BLOCK_COLORS: Record<string, number> = {
  air: 0x000000,
  grass: 0x8dd27f,
  dirt: 0xbf8f67,
  sand: 0xf4e3ad,
  stone: 0xb9bcc9,
  water: 0x7ec9f0,
  log: 0xa97c55,
  leaves: 0x6fc48d,
  "berry bush": 0xd47f99,
  "coal ore": 0x7a7585,
  "iron ore": 0xe0a884,
  planks: 0xe6bd85,
  workbench: 0xcf9152,
  furnace: 0x8d8a99,
  torch: 0xffd56a,
  door: 0xbd7f45,
  chest: 0xb07a3e,
  sprout: 0x9fd86b,
  wheat: 0xe8c95a,
  bed: 0xd9675f,
};

/** Top faces of grass and leaves are a touch brighter, sides a touch different. */
export const TOP_TINT: Record<string, number> = {
  grass: 0x9ee08c,
  log: 0xcaa67c,
  "berry bush": 0xe493ab,
  workbench: 0xdfa86a,
  chest: 0xc99556,
  bed: 0xf4efe6,
};

export const SIDE_TINT: Record<string, number> = {
  grass: 0x86c27a,
};

export const TRANSPARENT = new Set(["air", "water", "torch"]);

// Face shade by direction: +y, -y, +x, -x, +z, -z
export const FACE_SHADE = [1.0, 0.55, 0.86, 0.8, 0.9, 0.76];

export const SKY = {
  day: { sky: 0xa8dcf5, horizon: 0xe9f5fb, ground: 0xbfe3a6, sun: 0xfff2d6, ambient: 0.75 },
  dusk: { sky: 0xf2a8b7, horizon: 0xffd9a3, ground: 0xb79fb0, sun: 0xffb27a, ambient: 0.5 },
  night: { sky: 0x222a4d, horizon: 0x4a5287, ground: 0x2a3050, sun: 0x9fb0ff, ambient: 0.28 },
};

export const CREATURE_COLORS = {
  sheepWool: 0xfbf6ee,
  sheepFace: 0xf2c2b6,
  sheepLeg: 0xd9b8a8,
  chickenBody: 0xfffaf2,
  chickenBeak: 0xffb347,
  chickenComb: 0xff7b8a,
  chickenLeg: 0xf7a24d,
  zombieSkin: 0x9ad8a8,
  zombieShirt: 0x5d8fb5,
  zombiePants: 0x4f5e8c,
  zombieEye: 0x2f2a3a,
  zombieEyeWhite: 0xfcfcff,
  agentSkin: 0xf9d7bd,
  agentShirt: 0x7fb0ea,
  agentPants: 0x5a6aa8,
  agentHair: 0x6b4a3a,
  eye: 0x2b2733,
  mouth: 0xd98079,
};
