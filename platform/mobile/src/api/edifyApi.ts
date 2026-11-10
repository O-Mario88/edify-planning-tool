/** The gateway calls the app makes, typed by the generated contracts. */
import type { Session } from '../gen/edify/identity/v1/identity_pb';
import { IdentityService } from '../gen/edify/identity/v1/identity_pb';
import type {
  GetMyPortfolioSummaryResponse,
  ListMySchoolsResponse,
} from '../gen/edify/schools/v1/schools_pb';
import { SchoolService } from '../gen/edify/schools/v1/schools_pb';
import type {
  GetHomeQueueResponse,
  GetHomeResponse,
  GetHomeTodoFiguresResponse,
} from '../gen/edify/screens/v1/home_pb';
import { HomeScreenService } from '../gen/edify/screens/v1/home_pb';
import type { GetNavigationResponse } from '../gen/edify/screens/v1/navigation_pb';
import { NavigationService } from '../gen/edify/screens/v1/navigation_pb';
import type {
  GetSchoolDirectoryRequest,
  GetSchoolDirectoryResponse,
} from '../gen/edify/screens/v1/school_directory_pb';
import { SchoolDirectoryScreenService } from '../gen/edify/screens/v1/school_directory_pb';
import type {
  AddToClusterForm,
  AddToClusterRequest,
  AddToProjectForm,
  AddToProjectRequest,
  BulkActionResult,
  SchoolActionResult,
} from '../gen/edify/screens/v1/school_actions_pb';
import { SchoolActionService } from '../gen/edify/screens/v1/school_actions_pb';
import type {
  GetSchoolProfileRequest,
  GetSchoolProfileResponse,
} from '../gen/edify/screens/v1/school_profile_pb';
import { SchoolProfileService } from '../gen/edify/screens/v1/school_profile_pb';
import type { GetDrawerOptionsRequest, PageDrawer, GetDrawerResponse, SaveDrawerResponse, SaveSchoolDrawerResponse } from '../gen/edify/screens/v1/drawer_pb';
import type { DrawerOption } from '../gen/edify/screens/v1/form_pb';
import { PageDrawerService, SchoolDrawerService } from '../gen/edify/screens/v1/drawer_pb';
import type { GetExportResponse } from '../gen/edify/screens/v1/export_pb';
import { ExportService } from '../gen/edify/screens/v1/export_pb';
import type {
  GetPlanningDrawerResponse,
  GetTrainingCapacityRequest,
  GetTrainingCapacityResponse,
  SavePlanningDrawerResponse,
} from '../gen/edify/screens/v1/planning_drawer_pb';
import { PlanningDrawerService } from '../gen/edify/screens/v1/planning_drawer_pb';
import type { GetMyPlanResponse } from '../gen/edify/screens/v1/my_plan_pb';
import { MyPlanScreenService } from '../gen/edify/screens/v1/my_plan_pb';
import type { GetPageResponse } from '../gen/edify/screens/v1/page_screen_pb';
import { PageScreenService } from '../gen/edify/screens/v1/page_screen_pb';

import type {
  AssignLeaderRequest,
  AssignLeaderResponse,
  EndAssignmentResponse,
  GetClusterHomeResponse,
  GetMyClustersResponse,
  ListLeadersResponse,
  ListManagedClustersResponse,
  ListMemberSchoolsResponse,
  ReplaceLeaderResponse,
} from '../gen/edify/clusters/v1/leadership_pb';
import { ClusterLeadershipService } from '../gen/edify/clusters/v1/leadership_pb';

/** A request message's own fields, without the generated bookkeeping. */
type Fields<T> = Partial<Omit<T, '$typeName' | '$unknown'>>;
import { ApiError, callUnary } from './connect';
import type { ConnectTransport } from './connect';

export interface EdifyApi {
  getSession(): Promise<Session>;
  listMySchools(options: { page: number; pageSize: number; search: string }): Promise<ListMySchoolsResponse>;
  getMyPortfolioSummary(): Promise<GetMyPortfolioSummaryResponse>;
  getHome(): Promise<GetHomeResponse>;
  getHomeQueue(): Promise<GetHomeQueueResponse>;
  getHomeTodoFigures(): Promise<GetHomeTodoFiguresResponse>;
  getNavigation(): Promise<GetNavigationResponse>;
  getSchoolDirectory(
    query: Partial<Omit<GetSchoolDirectoryRequest, '$typeName' | '$unknown'>>,
  ): Promise<GetSchoolDirectoryResponse>;
  getAddToCluster(schoolId: string): Promise<AddToClusterForm>;
  addToCluster(request: Fields<AddToClusterRequest>): Promise<SchoolActionResult>;
  getAddToProject(schoolId: string): Promise<AddToProjectForm>;
  addToProject(request: Fields<AddToProjectRequest>): Promise<SchoolActionResult>;
  bulkAssignCluster(schoolIds: readonly string[], clusterId: string): Promise<BulkActionResult>;
  bulkAssignProject(schoolIds: readonly string[], projectId: string): Promise<BulkActionResult>;
  getSchoolProfile(request: Fields<GetSchoolProfileRequest>): Promise<GetSchoolProfileResponse>;
  getSchoolDrawer(schoolId: string, kind: string): Promise<PageDrawer>;
  saveSchoolDrawer(
    schoolId: string,
    kind: string,
    values: Readonly<Record<string, string>>,
  ): Promise<SaveSchoolDrawerResponse>;
  getDrawerOptions(request: Fields<GetDrawerOptionsRequest>): Promise<DrawerOption[]>;
  /** Schedule visit or Assign to Partner: the drawer, or the web's refusal. */
  getPlanningDrawer(schoolId: string, kind: string): Promise<GetPlanningDrawerResponse>;
  savePlanningDrawer(
    schoolId: string,
    kind: string,
    values: Readonly<Record<string, string>>,
  ): Promise<SavePlanningDrawerResponse>;
  getTrainingCapacity(request: Fields<GetTrainingCapacityRequest>): Promise<GetTrainingCapacityResponse>;
  /** My Plan for the page's own query (its tabs, filters and pagers). */
  getMyPlan(query: Readonly<Record<string, string>>): Promise<GetMyPlanResponse>;
  /** Any page the app draws from its components, with its own query. */
  getPage(path: string, query: Readonly<Record<string, string>>): Promise<GetPageResponse>;
  /** Any drawer a page opens, by its web path and query. */
  getDrawer(path: string): Promise<GetDrawerResponse>;
  /** Save a drawer by its path, or (with `form`) a form the page at `path` shows itself. */
  saveDrawer(path: string, values: Readonly<Record<string, string>>, form?: string): Promise<SaveDrawerResponse>;
  /** How an export is coming along, and its download link once ready. */
  getExport(jobId: string): Promise<GetExportResponse>;
  // The Cluster Leader Portal (edify.clusters.v1.ClusterLeadershipService).
  getMyClusters(): Promise<GetMyClustersResponse>;
  getClusterHome(clusterId: string): Promise<GetClusterHomeResponse>;
  listMemberSchools(clusterId: string, options: { page: number; search: string }): Promise<ListMemberSchoolsResponse>;
  listManagedClusters(options: { page: number; search: string }): Promise<ListManagedClustersResponse>;
  listLeaders(clusterId: string): Promise<ListLeadersResponse>;
  assignLeader(request: Fields<AssignLeaderRequest>): Promise<AssignLeaderResponse>;
  endAssignment(assignmentId: string, reason: string): Promise<EndAssignmentResponse>;
  replaceLeader(assignmentId: string, newUserId: string, reason: string): Promise<ReplaceLeaderResponse>;
}

export function createEdifyApi(transport: ConnectTransport): EdifyApi {
  return {
    async getSession() {
      const response = await callUnary(transport, IdentityService.method.getSession, {});
      if (!response.session) {
        throw new ApiError('The server sent no session.', 'internal', '', '');
      }
      return response.session;
    },
    listMySchools({ page, pageSize, search }) {
      return callUnary(transport, SchoolService.method.listMySchools, {
        page: { page, pageSize },
        search,
      });
    },
    getMyPortfolioSummary() {
      return callUnary(transport, SchoolService.method.getMyPortfolioSummary, {});
    },
    getHome() {
      return callUnary(transport, HomeScreenService.method.getHome, {});
    },
    getHomeQueue() {
      return callUnary(transport, HomeScreenService.method.getHomeQueue, {});
    },
    getHomeTodoFigures() {
      return callUnary(transport, HomeScreenService.method.getHomeTodoFigures, {});
    },
    getNavigation() {
      return callUnary(transport, NavigationService.method.getNavigation, {});
    },
    getSchoolDirectory(query) {
      return callUnary(transport, SchoolDirectoryScreenService.method.getSchoolDirectory, query);
    },
    getSchoolProfile(request) {
      return callUnary(transport, SchoolProfileService.method.getSchoolProfile, request);
    },
    async getSchoolDrawer(schoolId, kind) {
      const answer = await callUnary(transport, SchoolDrawerService.method.getSchoolDrawer, { schoolId, kind });
      if (!answer.drawer) {
        throw new ApiError('This drawer could not be loaded. Please try again.', 'internal', '', '');
      }
      return answer.drawer;
    },
    saveSchoolDrawer(schoolId, kind, values) {
      return callUnary(transport, SchoolDrawerService.method.saveSchoolDrawer, {
        schoolId,
        kind,
        values: { ...values },
      });
    },
    async getDrawerOptions(request) {
      const answer = await callUnary(transport, SchoolDrawerService.method.getDrawerOptions, request);
      return answer.options;
    },
    async getPlanningDrawer(schoolId, kind) {
      const answer = await callUnary(transport, PlanningDrawerService.method.getPlanningDrawer, { schoolId, kind });
      if (!answer.drawer && !answer.refusal) {
        throw new ApiError('This drawer could not be loaded. Please try again.', 'internal', '', '');
      }
      return answer;
    },
    savePlanningDrawer(schoolId, kind, values) {
      return callUnary(transport, PlanningDrawerService.method.savePlanningDrawer, {
        schoolId,
        kind,
        values: { ...values },
      });
    },
    getTrainingCapacity(request) {
      return callUnary(transport, PlanningDrawerService.method.getTrainingCapacity, request);
    },
    getMyPlan(query) {
      return callUnary(transport, MyPlanScreenService.method.getMyPlan, { query: { ...query } });
    },
    getDrawer(path) {
      return callUnary(transport, PageDrawerService.method.getDrawer, { path });
    },
    saveDrawer(path, values, form = '') {
      return callUnary(transport, PageDrawerService.method.saveDrawer, { path, values: { ...values }, form });
    },
    getExport(jobId) {
      return callUnary(transport, ExportService.method.getExport, { jobId });
    },
    getPage(path, query) {
      return callUnary(transport, PageScreenService.method.getPage, { path, query: { ...query } });
    },
    async getAddToCluster(schoolId) {
      const answer = await callUnary(transport, SchoolActionService.method.getAddToCluster, { schoolId });
      return required(answer.form);
    },
    async addToCluster(request) {
      const answer = await callUnary(transport, SchoolActionService.method.addToCluster, request);
      return required(answer.result);
    },
    async getAddToProject(schoolId) {
      const answer = await callUnary(transport, SchoolActionService.method.getAddToProject, { schoolId });
      return required(answer.form);
    },
    async addToProject(request) {
      const answer = await callUnary(transport, SchoolActionService.method.addToProject, request);
      return required(answer.result);
    },
    async bulkAssignCluster(schoolIds, clusterId) {
      const answer = await callUnary(transport, SchoolActionService.method.bulkAssignCluster, {
        schoolIds: [...schoolIds],
        clusterId,
      });
      return required(answer.result);
    },
    getMyClusters() {
      return callUnary(transport, ClusterLeadershipService.method.getMyClusters, {});
    },
    getClusterHome(clusterId) {
      return callUnary(transport, ClusterLeadershipService.method.getClusterHome, { clusterId });
    },
    listMemberSchools(clusterId, { page, search }) {
      return callUnary(transport, ClusterLeadershipService.method.listMemberSchools, {
        clusterId,
        search,
        page: { page, pageSize: 50 },
      });
    },
    listManagedClusters({ page, search }) {
      return callUnary(transport, ClusterLeadershipService.method.listManagedClusters, {
        search,
        page: { page, pageSize: 50 },
      });
    },
    listLeaders(clusterId) {
      return callUnary(transport, ClusterLeadershipService.method.listLeaders, { clusterId });
    },
    assignLeader(request) {
      return callUnary(transport, ClusterLeadershipService.method.assignLeader, request);
    },
    endAssignment(assignmentId, reason) {
      return callUnary(transport, ClusterLeadershipService.method.endAssignment, { assignmentId, reason });
    },
    replaceLeader(assignmentId, newUserId, reason) {
      return callUnary(transport, ClusterLeadershipService.method.replaceLeader, { assignmentId, newUserId, reason });
    },
    async bulkAssignProject(schoolIds, projectId) {
      const answer = await callUnary(transport, SchoolActionService.method.bulkAssignProject, {
        schoolIds: [...schoolIds],
        projectId,
      });
      return required(answer.result);
    },
  };
}

function required<T>(value: T | undefined): T {
  if (value === undefined) {
    throw new ApiError('The server sent an empty answer.', 'internal', '', '');
  }
  return value;
}
