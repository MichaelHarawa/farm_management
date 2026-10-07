// Explicit empty parameters also clear a batch/correction inherited by the tab.
// This changes navigation only; the original durable form and outbox remain.
export const recordMenuParams={workflow:'',batch:'',supersedes:''} as const;

export async function leaveUnsubmittedForm(write:Promise<void>,navigate:()=>void):Promise<void> {
  await write;
  navigate();
}
