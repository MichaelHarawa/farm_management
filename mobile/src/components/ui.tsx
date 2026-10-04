import React, { useEffect, useRef } from 'react';
import { AccessibilityInfo, ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { announceErrorChange, type ErrorAnnouncement } from './error-announcement';
export const colors = { cream: '#FAF6EB', navy: '#162D43', gold: '#BD922B', muted: '#45586A', border: '#D6CDB8', danger: '#992A27', white: '#FFFFFF' };
export function Screen({ title, children }: { title: string; children: React.ReactNode }) {
  return <SafeAreaView style={styles.safe} edges={['left', 'right', 'bottom']}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.screen}>
    <Text accessibilityRole="header" style={styles.title}>{title}</Text>{children}
  </ScrollView></SafeAreaView>;
}
export function Body({ children }: { children: React.ReactNode }) { return <Text style={styles.body}>{children}</Text>; }
export function Notice({ message }: { message: string | null }) {
  return message ? <Text accessible accessibilityLiveRegion="polite" style={styles.body}>{message}</Text> : null;
}
export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <View style={styles.card}><Text accessibilityRole="header" style={styles.heading}>{title}</Text>{children}</View>;
}
export function Button({ title, onPress, disabled = false, accessibilityLabel=title, selected }: { title: string; onPress: () => void; disabled?: boolean; accessibilityLabel?:string; selected?:boolean }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel} accessibilityState={{ disabled, ...(selected === undefined?{}:{selected}) }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => [styles.button, (disabled || pressed) && { opacity: 0.65 }]}><Text style={styles.buttonText}>{title}</Text></Pressable>;
}
export function Field({ label, ...props }: TextInputProps & { label: string }) {
  return <View style={styles.field}><Text style={styles.body}>{label}</Text><TextInput accessibilityLabel={label} placeholderTextColor={colors.muted} style={styles.input} {...props} /></View>;
}
export function ErrorMessage({ message, announcementKey }: { message: string | null; announcementKey?: number }) {
  const previous = useRef<ErrorAnnouncement | null>(null);
  useEffect(() => {
    previous.current = announceErrorChange(previous.current, { message, attempt: announcementKey }, text => {
      if (Platform.OS === 'android') AccessibilityInfo.announceForAccessibility(text);
    });
  }, [message, announcementKey]);
  // Explicit Android announcements work without moving focus to an off-screen
  // error. Avoid a second live-region announcement of the same native event.
  return message ? <Text accessible accessibilityRole="alert" accessibilityLiveRegion={Platform.OS === 'android' ? 'none' : 'polite'} style={styles.error}>{message}</Text> : null;
}
export function Loading({ label = 'Opening local records…' }: { label?: string }) {
  return <View accessible accessibilityRole="progressbar" accessibilityLabel={label} style={styles.card}><ActivityIndicator importantForAccessibility="no" color={colors.navy} /><Body>{label}</Body></View>;
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream }, screen: { padding: 20, gap: 16, flexGrow: 1, maxWidth: 700, width: '100%', alignSelf: 'center' },
  title: { color: colors.navy, fontSize: 30, fontWeight: '700' }, heading: { fontSize: 20, fontWeight: '600', color: colors.navy, marginBottom: 10 },
  body: { fontSize: 16, color: colors.muted, lineHeight: 25 }, card: { borderWidth: 1, borderColor: colors.border, borderLeftWidth: 4, borderLeftColor: colors.gold, borderRadius: 16, padding: 18, backgroundColor: colors.white, gap: 8 },
  button: { minHeight: 48, backgroundColor: colors.navy, padding: 14, borderRadius: 12, justifyContent: 'center' },
  buttonText: { fontSize: 16, color: colors.white, fontWeight: '600', textAlign: 'center' },
  field: { gap: 6 }, input: { minHeight: 52, borderWidth: 1, borderColor: colors.muted, borderRadius: 10, padding: 12, fontSize: 17, color: colors.navy, backgroundColor: colors.white },
  error: { fontSize: 16, lineHeight: 24, color: colors.danger },
});
