/** @typedef {{id:number,name:string,source:string,rows:number,row_count:number,storage_state:string,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,wait_reason:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{dataset_id:number,dataset_name:string,storage_state:string,state:string,operation:string,row_count:number,progress:number,stage:string,location:string,blocked_reason:string,waiting_jobs:number}} ColdArchive */
export {};
