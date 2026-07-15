export interface AuthenticatedUser {
  id: string;
  username: string;
  full_name: string;
  email: string | null;
  role: string;
  must_change_password: boolean;
}

