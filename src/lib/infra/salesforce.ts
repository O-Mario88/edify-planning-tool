// Salesforce sync adapter — Year-2 prep.
//
// Two implementations:
//
//   • `mock` — returns deterministic SmartMatch results synthesised
//     from the input. Lets the verification queue's "Salesforce ID"
//     column populate without an SF connection. Default.
//
//   • `jsforce` — live Salesforce via the `jsforce` SDK. Activated
//     when EDIFY_SALESFORCE_SYNC_ENABLED=1 plus credentials
//     (SF_LOGIN_URL, SF_USERNAME, SF_PASSWORD, optional SF_SECURITY_TOKEN).
//
// The adapter exposes a narrow surface:
//   • upsertActivity({...}) — push a verified PlannedActivity into the
//     Salesforce custom object, return the SF id
//   • matchActivity({...}) — find the existing SF activity that maps
//     to ours by (schoolId, date, kind), return a SmartMatch tier

import "server-only";

export type SmartMatchTier = "SMART_MATCH" | "POSSIBLE_MATCH" | "NO_MATCH" | "VERIFIED";

export type SalesforceUpsertInput = {
  ourId:           string;
  schoolSalesforceId?: string;
  ownerSalesforceId?:  string;
  kind:            string;
  date:            string;
  notes?:          string;
};

export type SalesforceMatchInput = {
  ourId:           string;
  schoolSalesforceId?: string;
  kind:            string;
  date:            string;
};

export type SalesforceAdapter = {
  label: string;
  isLive: boolean;
  upsertActivity(input: SalesforceUpsertInput): Promise<{ salesforceId: string; matchState: SmartMatchTier }>;
  matchActivity(input: SalesforceMatchInput): Promise<{ matchState: SmartMatchTier; salesforceId?: string }>;
};

// ────────── mock impl ──────────────────────────────────────────────

const mockAdapter: SalesforceAdapter = {
  label: "mock",
  isLive: false,
  async upsertActivity(input) {
    return {
      salesforceId: `0WO_DEMO_${djb2(input.ourId).toString(36)}`.toUpperCase(),
      matchState: input.schoolSalesforceId ? "SMART_MATCH" : "POSSIBLE_MATCH",
    };
  },
  async matchActivity(input) {
    return {
      matchState: input.schoolSalesforceId ? "SMART_MATCH" : "NO_MATCH",
      salesforceId: input.schoolSalesforceId
        ? `0WO_DEMO_${djb2(input.ourId).toString(36)}`.toUpperCase()
        : undefined,
    };
  },
};

// ────────── jsforce impl ───────────────────────────────────────────

function makeJsforceAdapter(): SalesforceAdapter {
  const loginUrl = process.env.SF_LOGIN_URL ?? "https://login.salesforce.com";
  const username = requireEnv("SF_USERNAME");
  const password = requireEnv("SF_PASSWORD") + (process.env.SF_SECURITY_TOKEN ?? "");

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let conn: any = null;
  async function getConn(): Promise<unknown> {
    if (conn) return conn;
    let jsforceMod: unknown;
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const dynamicRequire: any = (0, eval)("require");
      jsforceMod = dynamicRequire("jsforce");
    } catch (err) {
      throw new Error(`jsforce not installed: ${String(err)}`);
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    conn = new (jsforceMod as any).Connection({ loginUrl });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (conn as any).login(username, password);
    return conn;
  }

  return {
    label: "jsforce",
    isLive: true,
    async upsertActivity(input) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c: any = await getConn();
      const res = await c.sobject("Edify_Activity__c").upsert(
        {
          Edify_Internal_Id__c: input.ourId,
          School__c: input.schoolSalesforceId,
          OwnerId: input.ownerSalesforceId,
          Activity_Kind__c: input.kind,
          Activity_Date__c: input.date,
          Notes__c: input.notes,
        },
        "Edify_Internal_Id__c",
      );
      return {
        salesforceId: res?.id ?? "",
        matchState: input.schoolSalesforceId ? "SMART_MATCH" : "POSSIBLE_MATCH",
      };
    },
    async matchActivity(input) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c: any = await getConn();
      const q = `SELECT Id FROM Edify_Activity__c WHERE Edify_Internal_Id__c = '${escapeSoql(input.ourId)}' LIMIT 1`;
      const res = await c.query(q);
      const id = res?.records?.[0]?.Id;
      if (id) return { matchState: "SMART_MATCH", salesforceId: id };
      if (input.schoolSalesforceId) return { matchState: "POSSIBLE_MATCH" };
      return { matchState: "NO_MATCH" };
    },
  };
}

function escapeSoql(s: string): string {
  return s.replace(/'/g, "\\'");
}

function djb2(str: string): number {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return h >>> 0;
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveSalesforce(): SalesforceAdapter {
  if (process.env.EDIFY_SALESFORCE_SYNC_ENABLED === "1") {
    try { return makeJsforceAdapter(); }
    catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] salesforce: jsforce config failed; using mock. Reason:", String(err));
    }
  }
  return mockAdapter;
}
