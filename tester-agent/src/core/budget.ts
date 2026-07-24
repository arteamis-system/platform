// Hard ceilings for an agent run (NFR-4, TRD §7.6). Whichever limit is hit first
// ends the loop. A run can never exceed its declared iteration, wall-clock, or
// USD cap.

export interface BudgetLimits {
  iterations: number;
  wallClockMs: number;
  tokenUsd: number;
}

export type StopReason = 'iterations' | 'wallclock' | 'budget' | 'dry' | null;

export class Budget {
  private spentUsd = 0;
  private iteration = 0;
  private dryStreak = 0;

  constructor(
    private readonly limits: BudgetLimits,
    private readonly startedAtMs: number,
    private readonly dryStopAfter = 3,
  ) {}

  /** Reason to stop *before* running another iteration, or null to continue. */
  stopReason(nowMs: number): StopReason {
    if (this.iteration >= this.limits.iterations) return 'iterations';
    if (nowMs - this.startedAtMs >= this.limits.wallClockMs) return 'wallclock';
    if (this.spentUsd >= this.limits.tokenUsd) return 'budget';
    if (this.dryStreak >= this.dryStopAfter) return 'dry';
    return null;
  }

  startIteration(): number {
    this.iteration += 1;
    return this.iteration;
  }

  /** Record spend and whether the iteration surfaced anything new. */
  record(costUsd: number, foundSomethingNew: boolean): void {
    this.spentUsd += Math.max(0, costUsd);
    this.dryStreak = foundSomethingNew ? 0 : this.dryStreak + 1;
  }

  get totalUsd(): number {
    return Number(this.spentUsd.toFixed(6));
  }

  get iterationsRun(): number {
    return this.iteration;
  }
}
