import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const cold={
 status:id=>api('/datasets/'+id+'/cold'),
 archives:()=>api('/cold-archives'),
 archive:id=>api('/datasets/'+id+'/cold/archive',{method:'POST'}),
 restore:id=>api('/datasets/'+id+'/cold/restore',{method:'POST'}),
 retry:id=>api('/datasets/'+id+'/cold/retry',{method:'POST'})
};
