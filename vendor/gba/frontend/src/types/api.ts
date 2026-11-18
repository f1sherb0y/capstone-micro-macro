export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message: string;
  error: null | {
    code: string;
    details: string[];
  };
}

export interface PageData<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
