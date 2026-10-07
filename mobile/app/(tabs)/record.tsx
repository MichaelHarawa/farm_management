import { useLocalSearchParams, router } from 'expo-router';
import { useSync } from '../../src/sync/context';
import { MortalityForm } from '../../src/components/mortality-form';
import { useSession } from '../../src/auth/session';
import { PoultryForm } from '../../src/components/poultry-form';
import { workflows, type Workflow } from '../../src/poultry/forms';
import { recordMenuParams } from '../../src/poultry/form-navigation';
import { Body, Button, Card, Screen } from '../../src/components/ui';
export default function Record(){
  const {store}=useSync();const {session}=useSession();const {supersedes,workflow,batch}=useLocalSearchParams<{supersedes?:string;workflow?:string;batch?:string}>();
  if(session?.capabilities.projection_version===2){
    if(workflow&&Object.hasOwn(workflows,workflow))return <PoultryForm key={`${session.pointer.partition}:${workflow}:${batch||'new'}:${supersedes||''}`} workflow={workflow as Workflow} batchId={batch||undefined} correctionId={supersedes||undefined}
      onChooseWorkflow={()=>router.setParams(recordMenuParams)}/>;
    if(supersedes)return <Screen title="Correction needs review"><Body>Return to Sync and open the matching workflow’s retained operation. No original evidence was edited.</Body></Screen>;
    return <Screen title="Record farm work"><Body>Local evidence first. Confirmed values change only after Django accepts each operation.</Body>
      {(Object.entries(workflows) as [Workflow,typeof workflows[Workflow]][]).filter(([,v])=>session.capabilities.commands[`${v.entity}.${v.action}`]?.available)
        .map(([key,value])=><Card key={key} title={value.title}><Button title={`Open ${value.title.toLowerCase()} form`}
          onPress={()=>router.push({pathname:'/(tabs)/record',params:{...recordMenuParams,workflow:key}})}/></Card>)}
    </Screen>;
  }
  return <MortalityForm key={`${store?.repository.identity.deploymentId}:${store?.repository.identity.actorId}:${supersedes??'new'}`} correctionId={supersedes}/>;
}
