import { Redirect, Tabs } from 'expo-router';
import { Pressable, Text, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSession } from '../../src/auth/session';
import { useQueueCount } from '../../src/components/queue';
import { colors } from '../../src/components/ui';
import { navigationColumns } from '../../src/components/navigation-layout';
export default function TabLayout() {
  const { session } = useSession();
  const queued = useQueueCount();
  const { width, fontScale } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const columns = navigationColumns(width, fontScale);
  if (!session) return <Redirect href="/" />;
  return <Tabs screenOptions={{ headerStyle: { backgroundColor: colors.navy }, headerTintColor: colors.white }}
    tabBar={({ state, descriptors, navigation }) => <View style={{ backgroundColor: colors.cream,
      borderTopWidth: 1, borderTopColor: colors.border, paddingBottom: insets.bottom,
      paddingLeft: insets.left, paddingRight: insets.right, flexDirection: 'row', flexWrap: 'wrap' }}>
      {state.routes.map((route, index) => {
        const title = descriptors[route.key]?.options.title ?? route.name;
        const selected = state.index === index;
        const count = route.name === 'sync' ? queued : null;
        return <Pressable key={route.key} accessibilityRole="tab" accessibilityState={{ selected }}
          accessibilityLabel={count && count > 0 ? `${title}, ${count} retained operations` : title}
          onPress={() => {
            const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
            if (!selected && !event.defaultPrevented) navigation.navigate(route.name, route.params);
          }}
          onLongPress={() => { navigation.emit({ type: 'tabLongPress', target: route.key }); }}
          style={({ pressed }) => ({ width: `${100 / columns}%`, minHeight: 48, padding: 10,
            justifyContent: 'center', borderTopWidth: 3, borderTopColor: selected ? colors.gold : 'transparent',
            backgroundColor: selected ? colors.white : colors.cream, opacity: pressed ? 0.65 : 1 })}>
          <Text style={{ fontSize: 12, lineHeight: 18, fontWeight: selected ? '700' : '500',
            textAlign: 'center', color: selected ? colors.navy : colors.muted }}>
            {title}{count && count > 0 ? ` (${count > 99 ? '99+' : count})` : ''}
          </Text>
        </Pressable>;
      })}
    </View>}>
    <Tabs.Screen name="today" options={{ title: 'Today' }} /><Tabs.Screen name="batches" options={{ title: 'Batches' }} />
    <Tabs.Screen name="record" options={{ title: 'Record' }} /><Tabs.Screen name="sync" options={{ title: 'Sync' }} />
    <Tabs.Screen name="more" options={{ title: 'More' }} />
  </Tabs>;
}
