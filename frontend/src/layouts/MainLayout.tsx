import React, { useState } from 'react'
import { Layout, Menu, Button, Typography, theme, Space } from 'antd'
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

const { Header, Sider, Content } = Layout
const { Text } = Typography

export const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const {
    token: { colorBgContainer },
  } = theme.useToken()

  const getSelectedMenuKey = (pathname: string) => {
    if (pathname.startsWith('/characters')) {
      return '/characters/library'
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
      key: '/characters/library',
      icon: <TeamOutlined />,
      label: '角色档案',
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
            <Button onClick={handleLogout}>退出登录</Button>
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
      </Layout>
    </Layout>
  )
}
