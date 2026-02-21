import axios from 'axios';
import type { InternalAxiosRequestConfig, AxiosError } from 'axios';

// Criar instância do axios com configuração base
const api = axios.create({
  // Default to same-origin to avoid hardcoding host ports and to work behind Nginx/Vite proxies.
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor de Request - Adicionar token JWT
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('@Saira:token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => {
    return Promise.reject(error);
  }
);

// Interceptor de Response - Tratar erro 401
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Limpar token e redirecionar para login
      localStorage.removeItem('@Saira:token');
      localStorage.removeItem('@Saira:user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
