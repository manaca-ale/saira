import axios from 'axios';

// Criar instância do axios com configuração base
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8001/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor de Request - Adicionar token JWT
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('@Saira:token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor de Response - Tratar erro 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
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
