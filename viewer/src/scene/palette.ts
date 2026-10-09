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
  "berry bush": 0x3f9a5a,
  "coal ore": 0x3d3a45,
  "iron ore": 0xe08a4f,
  planks: 0xe6bd85,
  workbench: 0xa8743f,
  furnace: 0x6f6873,
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
  workbench: 0xe8c08a,
  furnace: 0x57525e,
  chest: 0xc99556,
  bed: 0xf4efe6,
  "coal ore": 0xadafbd,
  "iron ore": 0xbdb5b6,
};

export const SIDE_TINT: Record<string, number> = {
  grass: 0x86c27a,
  "coal ore": 0xadafbd,
  "iron ore": 0xbdb5b6,
};

/** Cells the neighbours can be seen through: air, water, and the blocks drawn smaller than a cube. */
export const TRANSPARENT = new Set(["air", "water", "torch", "berry bush", "sprout", "wheat", "chest", "bed"]);

/** Detail colours for the blocks drawn with more than one colour (see terrain.ts). */
export const DETAIL = {
  berry: 0xe23a5a,
  bushTop: 0x52b06c,
  wheatStalk: 0xd9b84e,
  wheatHead: 0xf2cf5c,
  sproutLeaf: 0x8fd86b,
  benchGrid: 0x7a4f28,
  benchLeg: 0x7f532c,
  furnaceMouth: 0x2b2733,
  furnaceFire: 0xff8a33,
  chestLid: 0xc99556,
  chestBand: 0x6e4524,
  chestLatch: 0xffd56a,
  bedFrame: 0x8a5a32,
  bedPillow: 0xfbf6ee,
  ironShine: 0xf6c9a0,
};

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
