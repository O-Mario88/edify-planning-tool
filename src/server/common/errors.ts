// Framework-agnostic domain errors that replace Nest's HttpException family.
//
// Ported services throw these instead of BadRequestException/ForbiddenException/
// etc. Each carries an HTTP status so the surfaces dispatcher / route handlers
// can map a thrown error to a response — the job edify-api's global
// AllExceptionsFilter used to do.
export class DomainError extends Error {
  readonly status: number;
  readonly code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = new.target.name;
    this.status = status;
    this.code = code;
  }
}

export class BadRequestError extends DomainError {
  constructor(message = "Bad request", code?: string) {
    super(message, 400, code);
  }
}

export class UnauthorizedError extends DomainError {
  constructor(message = "Unauthorized", code?: string) {
    super(message, 401, code);
  }
}

export class ForbiddenError extends DomainError {
  constructor(message = "Forbidden", code?: string) {
    super(message, 403, code);
  }
}

export class NotFoundError extends DomainError {
  constructor(message = "Not found", code?: string) {
    super(message, 404, code);
  }
}

export class ConflictError extends DomainError {
  constructor(message = "Conflict", code?: string) {
    super(message, 409, code);
  }
}

/** Map any thrown value to an HTTP status + safe message for a route response. */
export function errorToResponse(err: unknown): { status: number; message: string; code?: string } {
  if (err instanceof DomainError) {
    return { status: err.status, message: err.message, code: err.code };
  }
  return { status: 500, message: "Internal server error" };
}
