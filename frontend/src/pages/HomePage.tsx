import React from 'react'
import { Alert, Button, Card, Col, Row, Space, Statistic, Typography } from 'antd'
import {
  CheckCircleOutlined,
  FolderOpenOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Title, Paragraph } = Typography

export const HomePage: React.FC = () => {
  const navigate = useNavigate()

  const stats = {
    activeFlow: 1,
    disabledFlows: 7,
    enabledBackendModules: 1,
  }

  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <Title level={2}>长视频主链路控制台</Title>
        <Paragraph type="secondary" style={{ fontSize: 16, maxWidth: 600, margin: '0 auto' }}>
          当前只保留一条稳定主链：输入创意描述，生成完整剧本，拆分成多个视频片段，
          为后续视频生成返回标准化 Prompt。
        </Paragraph>
        <Space size="large" style={{ marginTop: 24 }}>
          <Button
            type="primary"
            size="large"
            icon={<FolderOpenOutlined />}
            onClick={() => navigate('/projects')}
          >
            打开项目列表
          </Button>
          <Button
            size="large"
            icon={<ThunderboltOutlined />}
            onClick={() => navigate('/script-pipeline')}
          >
            继续当前项目
          </Button>
          <Button
            size="large"
            icon={<TeamOutlined />}
            onClick={() => navigate('/characters/library')}
          >
            角色档案库
          </Button>
        </Space>
      </div>

      <Row gutter={24} style={{ marginBottom: 48 }}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="保留主链"
              value={stats.activeFlow}
              prefix={<CheckCircleOutlined />}
              suffix="条"
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="停用旧流程"
              value={stats.disabledFlows}
              prefix={<ToolOutlined />}
              suffix="处"
              valueStyle={{ color: '#fa8c16' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="启用后端模块"
              value={stats.enabledBackendModules}
              prefix={<ThunderboltOutlined />}
              suffix="个"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="当前执行说明">
        <Alert
          type="info"
          showIcon
          message="当前仅保留主链路"
          description="前端现保留首页、视频生成页和独立角色档案页；后端仅注册 pipeline 路由。旧的剧本 CRUD、地图管理、视频任务页、历史记录页等入口已停用。"
        />
      </Card>
    </div>
  )
}
