/**
 * The leader's follow-through (brief A2, A6, A7): action items with their
 * owner and due date, requests and concerns to the cluster's CCEO, and the
 * cluster management report for the financial year.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type {
  ActionItem,
  GetClusterReportResponse,
  LeaderRequest,
} from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import type { MemberSchool } from '../../gen/edify/clusters/v1/leadership_pb';
import { useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { DrawerButton } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { longDate } from './clusterRoutes';
import { Field, Muted, Notice, OpsCard, OpsTitle, SectionLabel, StateBadge, opsStyles } from './opsParts';

const METHOD = ClusterMobilizationService.method;

interface ClusterProps {
  readonly clusterId: string;
  readonly clusterName: string;
}

export function ActionItemsScreen({ clusterId, clusterName }: ClusterProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [items, setItems] = useState<readonly ActionItem[]>([]);
  const [members, setMembers] = useState<readonly MemberSchool[]>([]);
  const [title, setTitle] = useState('');
  const [ownerSchool, setOwnerSchool] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [dueOn, setDueOn] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(() => {
    api
      .call(METHOD.listActionItems, { clusterId })
      .then((answer) => setItems(answer.items))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);
  useEffect(load, [load]);
  useEffect(() => {
    api
      .listMemberSchools(clusterId, { page: 1, search: '' })
      .then((answer) => setMembers(answer.schools))
      .catch(() => undefined);
  }, [api, clusterId]);

  const run = (work: Promise<unknown>, message: string, reset?: () => void) => {
    setIsBusy(true);
    setError('');
    work
      .then(() => {
        setNotice(message);
        reset?.();
        load();
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <OpsTitle eyebrow={clusterName} title="Action items" copy="What the cluster agreed to do, who owns it and by when." />
      <Notice text={notice} />
      <Notice text={error} isError />
      <OpsCard>
        <SectionLabel>New action item</SectionLabel>
        <Field label="What is to be done" value={title} onChange={setTitle} />
        <Select
          label="Owner school"
          value={ownerSchool}
          choices={members.map((s) => ({ value: s.id, label: `${s.name} (${s.schoolId})` }))}
          placeholder="A member school, or name a person below"
          onChange={setOwnerSchool}
          variant="form"
        />
        {ownerSchool ? null : <Field label="Owner's name" value={ownerName} onChange={setOwnerName} />}
        <DateField label="Due" value={dueOn} onChange={setDueOn} placeholder="No due date" />
        <DrawerButton
          label="Add"
          isPrimary
          isBusy={isBusy}
          isDisabled={!title.trim() || (!ownerSchool && !ownerName.trim())}
          onPress={() =>
            run(api.call(METHOD.saveActionItem, { clusterId, title, ownerSchoolId: ownerSchool, ownerName, dueOn }), 'Action item added.', () => {
              setTitle('');
              setOwnerName('');
              setOwnerSchool('');
              setDueOn('');
            })
          }
        />
      </OpsCard>
      {items.length === 0 ? <Muted>No action item yet.</Muted> : null}
      {items.map((item) => (
        <OpsCard key={item.id}>
          <View style={opsStyles.spread}>
            <View style={opsStyles.grow}>
              <Text style={[opsStyles.name, { color: colors.text }]}>{item.title}</Text>
              <Text style={[opsStyles.meta, { color: item.isOverdue ? colors.danger : colors.textMuted }]}>
                {item.owner || 'No owner'} · {item.dueOn ? `due ${longDate(item.dueOn)}` : 'no due date'}
                {item.isOverdue ? ' · overdue' : ''}
              </Text>
            </View>
            <StateBadge state={item.status} />
          </View>
          {item.status === 'open' ? (
            <View style={opsStyles.actions}>
              <DrawerButton label="Done" isBusy={isBusy} onPress={() => run(api.call(METHOD.closeActionItem, { id: item.id, status: 'done' }), 'Marked done.')} />
              <DrawerButton label="Cancel item" isBusy={isBusy} onPress={() => run(api.call(METHOD.closeActionItem, { id: item.id, status: 'cancelled' }), 'Cancelled.')} />
            </View>
          ) : null}
        </OpsCard>
      ))}
    </ScrollView>
  );
}

export function RequestsScreen({ clusterId, clusterName }: ClusterProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [requests, setRequests] = useState<readonly LeaderRequest[]>([]);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(() => {
    api
      .call(METHOD.listRequests, { clusterId })
      .then((answer) => setRequests(answer.requests))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);
  useEffect(load, [load]);

  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <OpsTitle eyebrow={clusterName} title="Requests to staff" copy="Ask your CCEO for help, or raise a concern about the cluster." />
      <Notice text={notice} />
      <Notice text={error} isError />
      <OpsCard>
        <Field label="Subject" value={subject} onChange={setSubject} />
        <Field label="What you need" value={body} onChange={setBody} isMultiline />
        <DrawerButton
          label="Send to your CCEO"
          isPrimary
          isBusy={isBusy}
          isDisabled={!subject.trim() || !body.trim()}
          onPress={() => {
            setIsBusy(true);
            api
              .call(METHOD.submitRequest, { clusterId, subject, body })
              .then(() => {
                setNotice('Sent. The answer appears here.');
                setSubject('');
                setBody('');
                load();
              })
              .catch((cause: unknown) => setError(describe(cause)))
              .finally(() => setIsBusy(false));
          }}
        />
      </OpsCard>
      {requests.map((request) => (
        <OpsCard key={request.id}>
          <View style={opsStyles.spread}>
            <Text style={[opsStyles.name, { color: colors.text, flex: 1 }]}>{request.subject}</Text>
            <StateBadge state={request.status} />
          </View>
          <Muted>{request.body}</Muted>
          {request.answer ? (
            <Text style={[opsStyles.meta, { color: colors.success }]}>
              {request.answeredBy}: {request.answer}
            </Text>
          ) : null}
        </OpsCard>
      ))}
    </ScrollView>
  );
}

export function ClusterReportScreen({ clusterId, clusterName }: ClusterProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [report, setReport] = useState<GetClusterReportResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .call(METHOD.getClusterReport, { clusterId })
      .then(setReport)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);

  if (!report) {
    return (
      <ScrollView contentContainerStyle={opsStyles.page}>
        {error ? <Notice text={error} isError /> : <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />}
      </ScrollView>
    );
  }
  return (
    <ScrollView contentContainerStyle={opsStyles.page}>
      <OpsTitle eyebrow={clusterName} title="Cluster report" copy={`${report.period}: from the cluster's activities and your records.`} />
      <OpsCard>
        {report.figures.map((figure) => (
          <View key={figure.key} style={opsStyles.spread}>
            <Text style={[opsStyles.meta, { color: colors.text, fontSize: 13 }]}>{figure.label}</Text>
            <Text style={[opsStyles.name, { color: colors.text }]}>{figure.value}</Text>
          </View>
        ))}
      </OpsCard>
      <SectionLabel>Schools repeatedly absent</SectionLabel>
      <OpsCard>
        {report.repeatedlyAbsent.length === 0 ? <Muted>No school was absent from two or more held activities.</Muted> : null}
        {report.repeatedlyAbsent.map((school) => (
          <View key={school.schoolId} style={opsStyles.spread}>
            <Text style={[opsStyles.meta, { color: colors.text, flex: 1, fontSize: 13 }]}>
              {school.name} ({school.edifySchoolId})
            </Text>
            <Text style={[opsStyles.name, { color: colors.danger }]}>
              {school.absences} of {school.invitations}
            </Text>
          </View>
        ))}
      </OpsCard>
      <Counts title="Trainings held, by intervention" counts={report.trainingByIntervention} empty="No cluster training held this year yet." />
      <Counts title="Member schools by SSA status" counts={report.ssaStatus} empty="No member school." />
      <Counts title="Waiting on staff" counts={report.needsStaff} empty="Nothing." />
    </ScrollView>
  );
}

function Counts({ title, counts, empty }: { readonly title: string; readonly counts: readonly { label: string; count: number }[]; readonly empty: string }) {
  const { colors } = useTheme();
  return (
    <>
      <SectionLabel>{title}</SectionLabel>
      <OpsCard>
        {counts.length === 0 ? <Muted>{empty}</Muted> : null}
        {counts.map((count) => (
          <View key={count.label} style={opsStyles.spread}>
            <Text style={[opsStyles.meta, { color: colors.text, fontSize: 13 }]}>{count.label.replace(/_/g, ' ')}</Text>
            <Text style={[opsStyles.name, { color: colors.text }]}>{count.count}</Text>
          </View>
        ))}
      </OpsCard>
    </>
  );
}
