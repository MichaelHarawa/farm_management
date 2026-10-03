import { Stack } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { SessionProvider } from '../src/auth/session';
import { colors } from '../src/components/ui';
import { SyncProvider } from '../src/sync/context';
export default function RootLayout() {
  return <SafeAreaProvider><SessionProvider><SyncProvider><Stack screenOptions={{ headerStyle: { backgroundColor: colors.navy }, headerTintColor: colors.white }}>
    <Stack.Screen name="index" options={{ title: 'Farm Management' }} /><Stack.Screen name="(tabs)" options={{ headerShown: false }} />
    <Stack.Screen name="native-storage-check" options={{ title: 'Native storage checks' }} />
    <Stack.Screen name="native-sync-check" options={{ title: 'Phase4 synthetic checks' }} />
    <Stack.Screen name="batch/[id]" options={{title:'Downloaded batch'}} />
  </Stack></SyncProvider></SessionProvider></SafeAreaProvider>;
}
