import axios from 'axios'

const http = axios.create({
  baseURL: '',
  withCredentials: true,
  timeout: 30000,
})

http.interceptors.response.use(
  (res) => res,
  (err: any) => {
    if (err.response && err.response.status === 401) {
      if (!location.pathname.startsWith('/login')) {
        location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

export default http
