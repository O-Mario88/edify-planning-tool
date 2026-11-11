/**
 * The leader's follow-through (brief A2, A6): action items with their owner
 * and due date, and requests and concerns to the cluster's CCEO. The report
 * is Progress & Reports (ProgressScreen).
 */
import { useCallback, useEffect, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ActionItem, LeaderRequest } from '../../gen/edify/clusters/v1/mobilization_pb';
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
