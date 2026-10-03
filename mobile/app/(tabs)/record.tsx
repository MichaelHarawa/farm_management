import { useLocalSearchParams } from 'expo-router';
import { useSync } from '../../src/sync/context';
import { MortalityForm } from '../../src/components/mortality-form';
export default function Record(){
  const {store}=useSync();const {supersedes}=useLocalSearchParams<{supersedes?:string}>();
  return <MortalityForm key={`${store?.repository.identity.deploymentId}:${store?.repository.identity.actorId}:${supersedes??'new'}`} correctionId={supersedes}/>;
}
