/**
 * Carregamento assíncrono com estados de carga, erro e recarga.
 *
 * Existe para que cada página do Control não reescreva o mesmo
 * `useState`/`useEffect`/flag de cancelamento. Não substitui uma camada de
 * cache de servidor — o projeto não usa TanStack Query, e introduzir uma
 * dependência nova só por causa destas telas não se justifica.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncDataState<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
  reload: () => void;
}

const messageFrom = (error: unknown): string => {
  const response = (error as { response?: { status?: number; data?: { detail?: string } } })?.response;
  if (response?.status === 403) {
    return 'Sua conta não tem acesso a esta área.';
  }
  if (response?.data?.detail) {
    return String(response.data.detail);
  }
  return 'Não foi possível carregar os dados. Tente novamente.';
};

export function useAsyncData<T>(loader: () => Promise<T>, deps: unknown[]): AsyncDataState<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // O loader muda de identidade a cada render; guardá-lo numa ref mantém o
  // efeito preso apenas às deps declaradas pela página.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    setError(null);

    loaderRef
      .current()
      .then((result) => {
        if (!active) return;
        setData(result);
      })
      .catch((cause) => {
        if (!active) return;
        setError(messageFrom(cause));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((current) => current + 1), []);

  return { data, isLoading, error, reload };
}
