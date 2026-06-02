import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { openaiConfigApi, OpenAIConfigUpdate } from '../services/api';

export function useOpenAIConfig() {
  return useQuery({
    queryKey: ['openaiConfig'],
    queryFn: () => openaiConfigApi.get(),
  });
}

export function useUpdateOpenAIConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: OpenAIConfigUpdate) => openaiConfigApi.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['openaiConfig'] });
    },
  });
}
