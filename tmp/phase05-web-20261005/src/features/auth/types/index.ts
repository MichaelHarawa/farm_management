export type UserRole = {
  slug: string;
  name: string;
};

export type AuthUser = {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  job_title: string;
  department: string;
  roles: UserRole[];
  is_staff: boolean;
  is_superuser: boolean;
};

export type LoginPayload = {
  username: string;
  password: string;
};

export type DjangoLoginResponse = {
  access: string;
  refresh: string;
  user: AuthUser;
};

export type DjangoRefreshResponse = {
  access: string;
  refresh?: string;
};

export type SessionResponse = {
  user: AuthUser;
};