export function prepare(value: string): string {
  return value;
}

export function present(value: string): string {
  return value;
}

export function shouldSchedule(
  prepared: string,
  ready: boolean,
  queued: number,
  capacity: number,
): boolean {
  return ready && prepared !== "" && queued < capacity;
}
