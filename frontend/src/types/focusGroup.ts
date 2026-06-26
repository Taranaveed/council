export interface FocusGroupInput {
  product_name: string;
  price: string;
  currency: string;
  target_audience: string;
  description: string;
}

export interface AgentTranscript {
  skeptic: string;
  bargain_hunter: string;
  target_fan: string;
}

export interface JudgeVerdict {
  summary: string;
  biggest_red_flag: string;
  biggest_selling_point: string;
  launch_score: number;
}

export interface FocusGroupResult {
  transcript: AgentTranscript;
  verdict: JudgeVerdict;
  raw_verdict?: string;
}
