import { AgentTheater } from './AgentTheater';

type Props = {
  steps: string[];
  /** ms per step before advancing (loops on last) */
  intervalMs?: number;
};

export function SteppedLoading({ steps, intervalMs = 6500 }: Props) {
  return <AgentTheater steps={steps} intervalMs={intervalMs} />;
}
