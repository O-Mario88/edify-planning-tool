// Storage adapter — file evidence (W6/W8).
//
// Two implementations:
//
//   • `dev` — generates a deterministic stub URI without touching disk.
//     Files aren't actually persisted; this is correct for the mock
//     mode where evidence is conceptual.
//
//   • `s3` — issues a presigned PUT URL the client uploads to directly.
//     Activated when AWS_S3_EVIDENCE_BUCKET is set in env. Uses
//     `@aws-sdk/client-s3` + `@aws-sdk/s3-request-presigner` (lazy
//     imported so dev installs don't pay for the SDK).
//
// Both implementations return a stable URI string the action layer
// stores on the entity. Production reads back via a separate signed-
// GET helper exposed below.

import "server-only";

export type UploadPlan = {
  /** The URI to persist on the entity (e.g. `s3://bucket/key`). */
  uri: string;
  /**
   * The URL the client should PUT bytes to. Empty in dev mode (the
   * dev impl doesn't store bytes). Present in S3 mode.
   */
  presignedPutUrl?: string;
  /** Method the client should use (always PUT for now). */
  method: "PUT" | "NONE";
  /** Seconds the presigned URL is valid for. */
  expiresInSec: number;
  /** Required request headers (e.g. Content-Type echoed back to S3). */
  headers: Record<string, string>;
};

export type StorageAdapter = {
  label: string;
  /**
   * Plan an upload for a given subject. Action handlers call this and
   * persist the returned URI on the entity even when the dev impl is
   * in use — the URI shape stays stable across adapters so swapping
   * doesn't break references.
   */
  planUpload(input: {
    kind: string;          // "training-participant" | "partner-activity" | …
    subjectId: string;
    filename: string;
    contentType?: string;
    contentLength: number;
  }): Promise<UploadPlan>;

  /**
   * Resolve a stored URI to a temporary signed-GET URL. Empty string
   * in dev mode. Used by the UI to render previews of uploaded
   * evidence.
   */
  signedGet(uri: string, expiresInSec?: number): Promise<string>;
};

// ────────── dev impl ────────────────────────────────────────────────

const devAdapter: StorageAdapter = {
  label: "dev",
  async planUpload(input) {
    const safeName = input.filename.replace(/[^a-zA-Z0-9._-]/g, "_");
    const uri = `s3://edify-evidence-dev/${input.kind}/${input.subjectId}/${Date.now()}-${safeName}`;
    return {
      uri,
      presignedPutUrl: undefined,
      method: "NONE",
      expiresInSec: 0,
      headers: {},
    };
  },
  async signedGet(uri) {
    // Dev: return the stored URI as-is — the UI can render it as
    // monospace text. The previewer treats `s3://` URIs as
    // "evidence on file" without trying to fetch them.
    return uri;
  },
};

// ────────── S3 impl ─────────────────────────────────────────────────
//
// Lazy-loaded. The SDK is heavy; we don't want to require dev installs
// to download it. Wrapped in a function so resolution happens once at
// first use, not at module load.

function makeS3Adapter(): StorageAdapter {
  const bucket = requireEnv("AWS_S3_EVIDENCE_BUCKET");
  const region = requireEnv("AWS_REGION");
  const expiresInSec = Number(process.env.AWS_S3_PRESIGN_TTL_SEC ?? 900);

  // Resolved at first call, not module load. Types are `unknown` so
  // the file typechecks even when @aws-sdk packages are not installed
  // (dev mode never reaches this code path). The lazy-loaded SDK is
  // brought in via require so a missing dep throws at runtime with a
  // clean message instead of a build-time error.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let s3: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let PutObjectCommand: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let GetObjectCommand: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let getSignedUrl: any = null;

  async function ensureSdk(): Promise<void> {
    if (s3) return;
    // (0, eval)('require') keeps the bundler from trying to resolve
    // these packages at build time. They're a runtime-only dep that
    // dev installs don't carry — see docs/INFRA_SETUP.md §2.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const dynamicRequire: any = (0, eval)("require");
    let sdk: unknown, presigner: unknown;
    try {
      sdk = dynamicRequire("@aws-sdk/client-s3");
      presigner = dynamicRequire("@aws-sdk/s3-request-presigner");
    } catch (err) {
      throw new Error(
        "AWS S3 SDK not installed. Run `npm i @aws-sdk/client-s3 @aws-sdk/s3-request-presigner`. " +
        `Underlying: ${String(err)}`,
      );
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { S3Client, PutObjectCommand: Put, GetObjectCommand: Get } = sdk as any;
    PutObjectCommand = Put;
    GetObjectCommand = Get;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    getSignedUrl = (presigner as any).getSignedUrl;
    s3 = new S3Client({ region });
  }

  return {
    label: `s3 (${bucket} · ${region})`,
    async planUpload(input) {
      await ensureSdk();
      const safeName = input.filename.replace(/[^a-zA-Z0-9._-]/g, "_");
      const key = `${input.kind}/${input.subjectId}/${Date.now()}-${safeName}`;
      const cmd = new PutObjectCommand({
        Bucket: bucket,
        Key: key,
        ContentType: input.contentType ?? "application/octet-stream",
        ContentLength: input.contentLength,
        ServerSideEncryption: "aws:kms",
      });
      const presignedPutUrl = await getSignedUrl(s3, cmd, { expiresIn: expiresInSec }) as string;
      const headers: Record<string, string> = {};
      if (input.contentType) headers["content-type"] = input.contentType;
      return {
        uri: `s3://${bucket}/${key}`,
        presignedPutUrl,
        method: "PUT",
        expiresInSec,
        headers,
      };
    },
    async signedGet(uri, expSec = expiresInSec) {
      await ensureSdk();
      const m = /^s3:\/\/([^/]+)\/(.+)$/.exec(uri);
      if (!m) throw new Error(`Not an S3 URI: ${uri}`);
      const cmd = new GetObjectCommand({ Bucket: m[1], Key: m[2] });
      return (await getSignedUrl(s3, cmd, { expiresIn: expSec })) as string;
    },
  };
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveStorage(): StorageAdapter {
  if (process.env.AWS_S3_EVIDENCE_BUCKET && process.env.AWS_REGION) {
    try {
      return makeS3Adapter();
    } catch (err) {
      // Fall through to dev so a misconfigured env doesn't crash boot.
      // Logged via observability once that's resolved (chicken-and-egg
      // at boot, hence the bare console here).
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] storage: S3 config failed; using dev. Reason:", String(err));
    }
  }
  return devAdapter;
}
