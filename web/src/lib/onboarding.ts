const IMAGE_ONBOARDING_STORAGE_KEY = "chatgpt2api:image_onboarding_intent";

export function markImageOnboardingIntent(mode: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(IMAGE_ONBOARDING_STORAGE_KEY, mode);
}

export function consumeImageOnboardingIntent() {
  if (typeof window === "undefined") {
    return null;
  }
  const value = window.sessionStorage.getItem(IMAGE_ONBOARDING_STORAGE_KEY);
  if (value) {
    window.sessionStorage.removeItem(IMAGE_ONBOARDING_STORAGE_KEY);
  }
  return value;
}
