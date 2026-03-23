import React, { useState } from 'react'
import { Alert, Button, Card, Form, Input, Space, Tabs, Typography, message } from 'antd'
import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { scriptPipelineApi } from '../services/api'
import { useAuthStore } from '../stores/auth'

const { Title, Paragraph } = Typography

export const LoginPage: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const token = useAuthStore((state) => state.token)
  const setAuth = useAuthStore((state) => state.setAuth)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (token) {
    return <Navigate to="/" replace />
  }

  const redirectTo = (location.state as { from?: string } | null)?.from || '/'

  const handleLogin = async (values: { account: string; password: string }) => {
    setLoading(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.login({
        account: values.account,
        password: values.password,
      })
      setAuth(response.data.access_token, response.data.user)
      message.success('登录成功')
      navigate(redirectTo, { replace: true })
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      setError(responseError.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async (values: { name: string; email: string; password: string }) => {
    setLoading(true)
    setError(null)
    try {
      const response = await scriptPipelineApi.register(values)
      setAuth(response.data.access_token, response.data.user)
      message.success('注册成功')
      navigate(redirectTo, { replace: true })
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      setError(responseError.response?.data?.detail || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background:
          'radial-gradient(circle at top left, rgba(17,78,140,0.22), transparent 35%), linear-gradient(135deg, #0e1b2c 0%, #183a63 48%, #d3aa50 100%)',
      }}
    >
      <Card style={{ width: '100%', maxWidth: 460, borderRadius: 18 }}>
        <Space direction="vertical" size={18} style={{ width: '100%' }}>
          <div>
            <Title level={2} style={{ marginBottom: 8 }}>
              用户登录
            </Title>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              登录后，当前视频生成流程会自动保存。刷新页面后可以继续当前阶段。
            </Paragraph>
          </div>

          {error ? <Alert type="error" showIcon message={error} /> : null}

          <Tabs
            items={[
              {
                key: 'login',
                label: '登录',
                children: (
                  <Form layout="vertical" onFinish={handleLogin}>
                    <Form.Item
                      label="邮箱或用户昵称"
                      name="account"
                      rules={[{ required: true, message: '请输入邮箱或用户昵称' }]}
                    >
                      <Input prefix={<UserOutlined />} placeholder="请输入邮箱或用户昵称" />
                    </Form.Item>
                    <Form.Item
                      label="密码"
                      name="password"
                      rules={[{ required: true, message: '请输入密码' }]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block loading={loading}>
                      登录
                    </Button>
                  </Form>
                ),
              },
              {
                key: 'register',
                label: '注册',
                children: (
                  <Form layout="vertical" onFinish={handleRegister}>
                    <Form.Item
                      label="用户名"
                      name="name"
                      rules={[{ required: true, message: '请输入用户名' }]}
                    >
                      <Input prefix={<UserOutlined />} placeholder="请输入用户名" />
                    </Form.Item>
                    <Form.Item
                      label="邮箱"
                      name="email"
                      rules={[{ required: true, message: '请输入邮箱' }]}
                    >
                      <Input prefix={<MailOutlined />} placeholder="请输入邮箱" />
                    </Form.Item>
                    <Form.Item
                      label="密码"
                      name="password"
                      rules={[
                        { required: true, message: '请输入密码' },
                        { min: 6, message: '密码至少 6 位' },
                      ]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block loading={loading}>
                      注册并登录
                    </Button>
                  </Form>
                ),
              },
            ]}
          />
        </Space>
      </Card>
    </div>
  )
}
