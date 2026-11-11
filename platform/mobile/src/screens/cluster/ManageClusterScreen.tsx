/**
 * "Manage Cluster" (owner's mockup, 2026-11-11): the leader's cluster in four
 * places — My Schools, School Contacts (whom to call to mobilise a school),
 * Cluster Details, and Training History. Everything here is read only; staff
 * keep the school and cluster records.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ChevronRight, FileText, MapPin, MessageSquare, Phone, User, Users } from 'lucide-react-native';
import type { LucideIcon } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ClusterActivity, ClusterSummary, MemberSchool } from '../../gen/edify/clusters/v1/leadership_pb';
import { ClusterLeadershipService } from '../../gen/edify/clusters/v1/leadership_pb';
import { fonts, radius, useTheme } from '../../theme';
import { LoanHero, LoanSheet } from '../loans/loanUi';
import { ActivityRow } from './ClusterHomeScreen';
import { useAllMembers } from './clusterData';
import { longDate } from './clusterRoutes';
import { Notice } from './opsParts';

type HubView = 'hub' | 'contacts' | 'details' | 'trainings';

interface ManageClusterProps {
  readonly cluster: ClusterSummary;
  readonly onOpenSchools: () => void;
  readonly onOpenActivity: (activityId: string) => void;
}

export function ManageClusterScreen({ cluster, onOpenSchools, onOpenActivity }: ManageClusterProps) {
  const { colors } = useTheme();
  const [view, setView] = useState<HubView>('hub');
  const back = () => setView('hub');
  if (view === 'contacts') {
    return <ContactsView cluster={cluster} onBack={back} />;
  }
  if (view === 'trainings') {
    return <TrainingsView cluster={cluster} onBack={back} onOpenActivity={onOpenActivity} />;
  }
  if (view === 'details') {
    return <DetailsView cluster={cluster} onBack={back} />;
  }
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={cluster.name} title="Manage Cluster" />
      <LoanSheet>
        <HubRow icon={Users} title={`My Schools (${cluster.memberSchoolCount})`} detail="View and manage schools" onPress={onOpenSchools} />
        <HubRow icon={User} title="School Contacts" detail="Directors and key contacts" onPress={() => setView('contacts')} />
        <HubRow icon={MapPin} title="Cluster Details" detail="View cluster information" onPress={() => setView('details')} />
        <HubRow icon={FileText} title="Training History" detail="Past trainings and attendance" onPress={() => setView('trainings')} />
        <Text style={[styles.muted, { color: colors.textSubtle }]}>
          A change to a school or the cluster goes to your CCEO through Requests to staff.
        </Text>
      </LoanSheet>
    </ScrollView>
  );
}

function HubRow({ icon: Icon, title, detail, onPress }: { readonly icon: LucideIcon; readonly title: string; readonly detail: string; readonly onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={[styles.hubRow, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Icon size={26} color={colors.primary} />
      <View style={styles.flex}>
        <Text style={[styles.hubTitle, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.muted, { color: colors.textMuted }]}>{detail}</Text>
      </View>
      <ChevronRight size={22} color={colors.textMuted} />
    </Pressable>
  );
}

function ContactsView({ cluster, onBack }: { readonly cluster: ClusterSummary; readonly onBack: () => void }) {
  const { colors } = useTheme();
  const members = useAllMembers(cluster.id);
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={cluster.name} title="School Contacts" onBack={onBack} />
      <LoanSheet>
        {members.error ? <Notice text={members.error} isError /> : null}
        {members.schools === null && !members.error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {members.schools?.map((school) => <ContactCard key={school.id} school={school} />)}
      </LoanSheet>
    </ScrollView>
  );
}

function ContactCard({ school }: { readonly school: MemberSchool }) {
  const { colors } = useTheme();
  const people = [
    school.directorName ? `Director: ${school.directorName}` : '',
    school.headteacherName ? `Head teacher: ${school.headteacherName}` : '',
    school.contactName && school.contactName !== school.directorName ? `Contact: ${school.contactName}` : '',
  ].filter(Boolean);
  const phones = [...new Set([school.contactPhone, school.schoolPhone].filter(Boolean))];
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Text style={[styles.hubTitle, { color: colors.text }]}>{school.name}</Text>
      <Text style={[styles.muted, { color: colors.textSubtle }]}>{[school.schoolId, school.district].filter(Boolean).join(' · ')}</Text>
      {people.map((person) => (
        <Text key={person} style={[styles.body, { color: colors.text }]}>
          {person}
        </Text>
      ))}
      {phones.length === 0 ? <Text style={[styles.muted, { color: colors.textMuted }]}>No phone number on record.</Text> : null}
      {phones.map((phone) => (
        <View key={phone} style={styles.phoneRow}>
          <Text style={[styles.body, styles.flex, { color: colors.text }]}>{phone}</Text>
          <Pressable onPress={() => void Linking.openURL(`tel:${phone}`)} accessibilityRole="button" accessibilityLabel={`Call ${phone}`} hitSlop={8} style={[styles.iconButton, { borderColor: colors.border }]}>
            <Phone size={18} color={colors.primary} />
          </Pressable>
          <Pressable onPress={() => void Linking.openURL(`sms:${phone}`)} accessibilityRole="button" accessibilityLabel={`Text ${phone}`} hitSlop={8} style={[styles.iconButton, { borderColor: colors.border }]}>
            <MessageSquare size={18} color={colors.primary} />
          </Pressable>
        </View>
      ))}
    </View>
  );
}

function DetailsView({ cluster, onBack }: { readonly cluster: ClusterSummary; readonly onBack: () => void }) {
  const { colors } = useTheme();
  const rows: readonly (readonly [string, string])[] = [
    ['Cluster', cluster.name],
    ['Type', cluster.clusterType],
    ['District', cluster.district],
    ['Sub-county', cluster.subCounty],
    ['Member schools', String(cluster.memberSchoolCount)],
    ['Responsible staff', cluster.responsibleStaff],
    ['You lead it since', cluster.myAssignment ? longDate(cluster.myAssignment.startsOn) : ''],
    ['Status', cluster.status],
  ];
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={cluster.name} title="Cluster Details" onBack={onBack} />
      <LoanSheet>
        <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
          {rows
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <View key={label} style={[styles.fact, { borderTopColor: colors.border }]}>
                {/* Owner 2026-11-12: "Label: value" on one line, the value in blue. */}
                <Text style={[styles.muted, { color: colors.textMuted }]}>
                  {label}: <Text style={[styles.factValue, { color: colors.link }]}>{value}</Text>
                </Text>
              </View>
            ))}
        </View>
        <Text style={[styles.muted, { color: colors.textSubtle }]}>Staff keep these details. Ask your CCEO through Requests to staff to change one.</Text>
      </LoanSheet>
    </ScrollView>
  );
}

function TrainingsView({ cluster, onBack, onOpenActivity }: { readonly cluster: ClusterSummary; readonly onBack: () => void; readonly onOpenActivity: (id: string) => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [trainings, setTrainings] = useState<readonly ClusterActivity[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api
      .call(ClusterLeadershipService.method.listActivities, { clusterId: cluster.id, when: 'past' })
      .then((answer) => setTrainings(answer.activities.filter((activity) => /training/i.test(activity.type))))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, cluster.id]);
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={cluster.name} title="Training History" subtitle="Cluster trainings of the last 120 days." onBack={onBack} />
      <LoanSheet>
        {error ? <Notice text={error} isError /> : null}
        {trainings === null && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {trainings?.length === 0 ? <Text style={[styles.muted, { color: colors.textMuted }]}>No cluster training in the last 120 days.</Text> : null}
        {trainings?.map((activity) => (
          <Pressable key={activity.id} onPress={() => onOpenActivity(activity.id)} accessibilityRole="button" accessibilityLabel={`Open ${activity.name}`}>
            <ActivityRow activity={activity} />
          </Pressable>
        ))}
      </LoanSheet>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  flex: { flex: 1, gap: 2 },
  hubRow: { flexDirection: 'row', alignItems: 'center', gap: 14, borderWidth: 1, borderRadius: radius.lg, padding: 16, minHeight: 72 },
  hubTitle: { fontFamily: fonts.bold, fontSize: 16 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  body: { fontFamily: fonts.medium, fontSize: 15 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 6 },
  phoneRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 4 },
  iconButton: { width: 44, height: 44, borderWidth: 1, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  fact: { borderTopWidth: StyleSheet.hairlineWidth, paddingVertical: 8 },
  factValue: { fontFamily: fonts.semibold, fontSize: 15 },
});
