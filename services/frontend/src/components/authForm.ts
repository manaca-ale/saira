export const primaryButton =
  "w-full py-3.5 bg-gradient-to-r from-[#efffc8] to-[#ccff33] text-black font-bold rounded-2xl disabled:opacity-50 disabled:cursor-not-allowed transition-all select-none";

// Mesma regra mínima do backend (app/core/password_policy.py); o backend confere o resto.
export function localPasswordProblem(password: string, confirm: string): string | null {
  if (password.length < 8) return "A senha precisa ter pelo menos 8 caracteres.";
  if (password.length > 128) return "A senha pode ter no máximo 128 caracteres.";
  if (password !== confirm) return "A confirmação não confere com a senha.";
  return null;
}
