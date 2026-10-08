import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { announceErrorChange, androidErrorMode, deferLiveError, liveErrorAccessibility, liveErrorLabel, liveErrorText, semanticErrorRegionKey, type ErrorAnnouncement } from './error-announcement';
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
export function ErrorMessage({ message, announcementKey, announce=true }: { message: string | null; announcementKey?: number; announce?:boolean }) {
  const previous = useRef<ErrorAnnouncement | null>(null);
  const mode=androidErrorMode(Platform.OS,Platform.Version,announce);
  const [delivered,setDelivered]=useState<ErrorAnnouncement|null>(null);
  useEffect(() => {
    let cancel:(()=>void)|undefined;
    previous.current = announceErrorChange(previous.current, { message:announce?message:null, attempt: announcementKey }, text => {
      if(mode==='legacy')AccessibilityInfo.announceForAccessibility(text);
      if(mode==='semantic')cancel=deferLiveError(text,value=>setDelivered({message:value,attempt:announcementKey}),work=>{
        const timer=setTimeout(work,100);return()=>clearTimeout(timer);
      });
    });
    return()=>cancel?.();
  }, [message, announcementKey, announce, mode]);
  // Android36 deprecates TYPE_ANNOUNCEMENT (used by RN's imperative API).
  // One summary at a time: real submissions replace its native node, initially
  // empty, then receive the full text. Redraws keep the same node. Quiet inline
  // errors never announce; no focus movement or duplicate imperative event.
  if(mode==='semantic') {
    const current={message,attempt:announcementKey};
    const text=liveErrorText(delivered,current);
    return <Text key={semanticErrorRegionKey(announcementKey)} {...liveErrorAccessibility(text)}
      accessibilityRole="alert" accessibilityLiveRegion="assertive"
      accessibilityLabel={liveErrorLabel(delivered,current)} style={styles.error}>{text}</Text>;
  }
  // Preserve previously verified legacy Android and other-platform behavior.
  return message ? <Text accessible accessibilityRole="alert" accessibilityLiveRegion={!announce||Platform.OS === 'android'?'none':'polite'} style={styles.error}>{message}</Text> : null;
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
