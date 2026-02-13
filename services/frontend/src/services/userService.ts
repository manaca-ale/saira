import api from './api';

export interface User {
  id: number;
  name: string;
  email: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active: boolean;
}

export interface CreateUserData {
  name: string;
  email: string;
  password: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active?: boolean;
}

function addStatusField(user: User): User & { status: string } {
  return { ...user, status: user.is_active ? 'Ativo' : 'Inativo' };
}

export async function getUsers(params?: { skip?: number; limit?: number }): Promise<(User & { status: string })[]> {
  const response = await api.get('/users/', { params });
  return response.data.map(addStatusField);
}

export const createUser = (data: CreateUserData) => api.post<User>('/users/', data).then(r => r.data);
export const updateUser = (id: number, data: Partial<CreateUserData>) => api.patch<User>(`/users/${id}`, data).then(r => r.data);
export const deleteUser = (id: number) => api.delete(`/users/${id}`);
