export type State = 'RECEIVED'|'PREVIEWING'|'PENDING_APPROVAL'|'READY'|'EXECUTING'|'UNKNOWN'|'SUCCEEDED'|'BLOCKED'|'REJECTED'|'EXPIRED'|'CANCELLED'|'STALE'|'FAILED'
export interface Change { table: string; id: number; before: Record<string, unknown>|null; after: Record<string,unknown>|null; kind: string; origin: string }
export interface Facts {
  coverage: string; direct_changed: number; cascade_changed: number; total_changed: number;
  changes: Change[]; preview_ms: number; created_at: number; recovery_status: string;
  limitations: string[]; query_result: { rows: Record<string,unknown>[]; truncated: boolean }|null
}
export interface Plan { plan_digest: string; view_digest: string; state_digest: string; schema_digest: string; policy_version: string; expires_at: number; scope: string; facts: Facts }
export interface Operation {
  id: string; state: State; decision: string|null; reason_code: string|null; version: number;
  created_at: number; updated_at: number; expires_at: number; tool: string; task: string; run_id: string; resource_id: string;
  summary: Pick<Facts,'coverage'|'direct_changed'|'cascade_changed'|'total_changed'|'preview_ms'>|null;
  result: { operation_id: string; plan_digest: string; committed_at: number; total_changed: number; query_result?: Facts['query_result'] }|null;
  error: { code: string; safe_message: string }|null;
  request?: Record<string,unknown>; plan?: Plan|null;
}
export interface Session { username: string; scope: string; csrf: string }
export interface Scenario { id: string; title: string; description: string; expected: string }
export interface Audit { items: { seq: number; ordinal: number; type: string; at: number; data: unknown; hash: string }[]; chain_valid: boolean; provided_approval_view: unknown }
export const stateNames: Record<State,string> = {
  RECEIVED:'已接收', PREVIEWING:'预检中', PENDING_APPROVAL:'等待审批', READY:'已授权，待执行',
  EXECUTING:'正在执行', UNKNOWN:'结果待核实', SUCCEEDED:'执行成功', BLOCKED:'策略阻断',
  REJECTED:'已拒绝', EXPIRED:'已过期', CANCELLED:'已取消', STALE:'快照已失效', FAILED:'执行失败',
}
export const toolNames: Record<string,string> = { 'db.query_rows':'读取记录', 'db.update_rows':'更新记录', 'db.delete_rows':'删除记录' }
export const timestamp = (value:number) => new Date(value*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})
