/** What a submission lacks, before the server is asked: one sentence, or none. */
export function registrationProblem(name: string, email: string, password: string): string | null {
  if (!name.trim()) return "Enter your name.";
  const [local, domain = ""] = email.trim().split("@");
  if (!local || !domain.includes(".")) return "Enter an email address, such as you@example.com.";
  if (password.length < 8) return "Use a password of at least 8 characters.";
  return null;
}
