import React, { useEffect, useState } from 'react'
import { Layout, Menu, Button, Typography, theme, Space, Modal, Input, message } from 'antd'
import {
  EnvironmentOutlined,
  FolderOpenOutlined,
  TeamOutlined,
  HomeOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../stores/auth'
import { useRuntimeSecretsStore } from '../stores/runtimeSecrets'

const { Header, Sider, Content } = Layout
const { Text } = Typography

export const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false)
  const [editingApiKey, setEditingApiKey] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const temporaryDoubaoApiKey = useRuntimeSecretsStore((state) => state.temporaryDoubaoApiKey)
  const apiKeyModalOpen = useRuntimeSecretsStore((state) => state.apiKeyModalOpen)
  const apiKeyModalReason = useRuntimeSecretsStore((state) => state.apiKeyModalReason)
  const setTemporaryDoubaoApiKey = useRuntimeSecretsStore((state) => state.setTemporaryDoubaoApiKey)
  const clearTemporaryDoubaoApiKey = useRuntimeSecretsStore((state) => state.clearTemporaryDoubaoApiKey)
  const closeApiKeyModal = useRuntimeSecretsStore((state) => state.closeApiKeyModal)
  const {
    token: { colorBgContainer },
  } = theme.useToken()

  useEffect(() => {
    if (apiKeyModalOpen) {
      setEditingApiKey(temporaryDoubaoApiKey)
    }
  }, [apiKeyModalOpen, temporaryDoubaoApiKey])

  const getSelectedMenuKey = (pathname: string) => {
    if (pathname.startsWith('/characters')) {
      return '/characters/subjects'
    }
    if (pathname.startsWith('/scenes')) {
      return '/scenes/library'
    }
    if (pathname.startsWith('/projects')) {
      return '/projects'
    }
    if (pathname.startsWith('/script-pipeline')) {
      return '/script-pipeline'
    }
    return '/'
  }

  // 菜单项
  const menuItems = [
    {
      key: '/',
      icon: <HomeOutlined />,
      label: '首页',
    },
    {
      key: '/projects',
      icon: <FolderOpenOutlined />,
      label: '项目列表',
    },
    {
      key: '/script-pipeline',
      icon: <ThunderboltOutlined />,
      label: '视频生成',
    },
    {
      key: '/characters/subjects',
      icon: <TeamOutlined />,
      label: '角色资产',
    },
    {
      key: '/scenes/library',
      icon: <EnvironmentOutlined />,
      label: '场景档案',
    },
  ]

  // 处理菜单点击
  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key)
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const handleLogin = () => {
    navigate('/login')
  }

  const handleSaveApiKey = () => {
    const normalized = editingApiKey.trim()
    if (!normalized) {
      message.warning('请输入 DOUBAO_API_KEY，或点击清除临时 Key')
      return
    }
    setTemporaryDoubaoApiKey(normalized)
    closeApiKeyModal()
    message.success('已保存到当前浏览器会话，可直接重试刚才的操作')
  }

  const handleClearApiKey = () => {
    clearTemporaryDoubaoApiKey()
    setEditingApiKey('')
    closeApiKeyModal()
    message.success('已清除当前浏览器会话中的临时 DOUBAO_API_KEY')
  }

  const isPublicLanding = location.pathname === '/' && !user

  if (isPublicLanding) {
    return (
      <Layout style={{ minHeight: '100vh', background: '#07111f' }}>
        <Header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            padding: '0 24px',
            background: 'rgba(7, 17, 31, 0.78)',
            backdropFilter: 'blur(18px)',
            borderBottom: '1px solid rgba(205, 178, 113, 0.18)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div
            style={{
              color: '#f6f2e8',
              fontSize: 18,
              fontWeight: 700,
              letterSpacing: '0.04em',
            }}
          >
            future of video
          </div>
          <Space size={12}>
            <Text style={{ color: 'rgba(246, 242, 232, 0.72)' }}>AI 视频生成工作台</Text>
            <Button type="primary" onClick={handleLogin}>
              登录
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: '0 24px 48px', background: 'transparent' }}>
          <Outlet />
        </Content>
        <Modal
          title="本次会话临时 DOUBAO_API_KEY"
          open={apiKeyModalOpen}
          onOk={handleSaveApiKey}
          onCancel={closeApiKeyModal}
          okText="保存并继续"
          cancelText="关闭"
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Text type="secondary">
              {apiKeyModalReason || '如果服务端未配置 DOUBAO_API_KEY，可在当前浏览器会话临时填写。关闭页面或清除后即失效。'}
            </Text>
            <Input.Password
              placeholder="输入 DOUBAO_API_KEY"
              value={editingApiKey}
              onChange={(event) => setEditingApiKey(event.target.value)}
            />
            {temporaryDoubaoApiKey ? (
              <Button danger type="link" style={{ padding: 0, width: 'fit-content' }} onClick={handleClearApiKey}>
                清除当前会话临时 Key
              </Button>
            ) : null}
          </Space>
        </Modal>
      </Layout>
    )
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        style={{
          background: '#001529',
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: collapsed ? 14 : 18,
            fontWeight: 'bold',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            padding: '0 16px',
          }}
        >
          {collapsed ? 'FoV' : 'future of video'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[getSelectedMenuKey(location.pathname)]}
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            padding: '0 24px',
            background: colorBgContainer,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{
              fontSize: '16px',
              width: 64,
              height: 64,
            }}
          />
          <Space size={16}>
            <Text type="secondary">{user ? `${user.name} · ${user.email}` : '未登录'}</Text>
            {user ? (
              <Button onClick={handleLogout}>退出登录</Button>
            ) : (
              <Button type="primary" onClick={handleLogin}>
                登录
              </Button>
            )}
          </Space>
        </Header>
        <Content
          style={{
            margin: 24,
            padding: 24,
            background: colorBgContainer,
            borderRadius: 8,
            minHeight: 280,
          }}
        >
          <Outlet />
        </Content>
        <Modal
          title="本次会话临时 DOUBAO_API_KEY"
          open={apiKeyModalOpen}
          onOk={handleSaveApiKey}
          onCancel={closeApiKeyModal}
          okText="保存并继续"
          cancelText="关闭"
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Text type="secondary">
              {apiKeyModalReason || '如果服务端未配置 DOUBAO_API_KEY，可在当前浏览器会话临时填写。关闭页面或清除后即失效。'}
            </Text>
            <Input.Password
              placeholder="输入 DOUBAO_API_KEY"
              value={editingApiKey}
              onChange={(event) => setEditingApiKey(event.target.value)}
            />
            {temporaryDoubaoApiKey ? (
              <Button danger type="link" style={{ padding: 0, width: 'fit-content' }} onClick={handleClearApiKey}>
                清除当前会话临时 Key
              </Button>
            ) : null}
          </Space>
        </Modal>
      </Layout>
    </Layout>
  )
}
