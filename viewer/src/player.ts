// Playback clock shared by every view on the page. pt is a fractional world step.

export const STEPS_PER_SECOND = 2;   // at 1x
export const SPEEDS = [1, 2, 5, 10, 20, 50];

export class Player {
  pt = 0;
  playing = false;
  speed = 5;
  /** Upper bound; the app refreshes it from the run(s). */
  maxT = 0;
  /** In live mode, stay at the newest step while playing. */
  live = false;
  private listeners: (() => void)[] = [];

  onChange(fn: () => void): void { this.listeners.push(fn); }
  private emit(): void { for (const fn of this.listeners) fn(); }

  tick(dt: number): void {
    if (!this.playing) return;
    const before = this.pt;
    this.pt = Math.min(this.maxT, this.pt + dt * STEPS_PER_SECOND * this.speed);
    if (this.pt >= this.maxT && !this.live) { this.pt = this.maxT; this.playing = false; }
    if (this.pt !== before) this.emit();
  }

  seek(t: number): void {
    this.pt = Math.max(0, Math.min(this.maxT, t));
    this.emit();
  }

  play(): void { if (this.pt >= this.maxT && !this.live) this.pt = 0; this.playing = true; this.emit(); }
  pause(): void { this.playing = false; this.emit(); }
  toggle(): void { this.playing ? this.pause() : this.play(); }
  setSpeed(s: number): void { this.speed = s; this.emit(); }

  get t(): number { return Math.floor(this.pt); }
}
