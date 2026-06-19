import "server-only";
import { prisma, type PrismaService } from "./prisma/prisma.service";
import { AuditService } from "./common/audit/audit.service";
import { ScopeService } from "./common/scope/scope.service";
import { AuthorizationService } from "./common/authz/authorization.service";

// Hand-rolled DI, replacing Nest's container. One instance of each service,
// all sharing the single PrismaClient. Services are stateless beyond their
// injected deps, so process-singletons are safe under Next's per-request model.
//
// As domains are ported (Wave 1+), their services are added here and the
// surfaces dispatcher calls `container.<service>.<method>(...)` in-process
// instead of proxying to edify-api.
class Container {
  readonly prisma: PrismaService = prisma;
  readonly audit = new AuditService(this.prisma);
  readonly scope = new ScopeService(this.prisma);
  readonly authz = new AuthorizationService(this.prisma, this.scope, this.audit);
}

const globalForContainer = globalThis as unknown as {
  __edifyContainer?: Container;
};

export const container: Container =
  globalForContainer.__edifyContainer ?? new Container();

if (process.env.NODE_ENV !== "production") {
  globalForContainer.__edifyContainer = container;
}
