export const Role={admin:'业务负责人',analyst:'分析员',viewer:'观察员'};
export const JobStatus={queued:'排队中',running:'计算中',waiting:'等待冷存取回',completed:'已完成',failed:'执行失败'};
export const StorageState={online:'在线',archiving:'正在冷存',cold:'已冷存',restoring:'取回中'};
export const ColdState={
 queued:'排队搬移',archiving:'搬移中',sealed:'冷存已核齐',restore_queued:'排队取回',restoring:'取回中',restored:'已取回',failed:'受阻待重试'
};
export function stateLabel(group,value){return (group==='storage'?StorageState:ColdState)[value]||value;}
