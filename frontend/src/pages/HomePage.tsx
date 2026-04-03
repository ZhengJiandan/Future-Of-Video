import React from 'react'
import { Button, Card, Col, Row, Space, Tag, Typography } from 'antd'
import {
  ArrowRightOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  PlayCircleOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/auth'

const { Title, Paragraph, Text } = Typography

const publicFeatureCards = [
  {
    title: '角色与场景资料沉淀',
    icon: <TeamOutlined />,
    label: 'Library First',
    description:
      '把参考图、角色设定、场景约束沉淀成可复用档案，减少连续片段里的角色漂移和世界观跳变。',
  },
  {
    title: '从剧本到片段连续生成',
    icon: <VideoCameraOutlined />,
    label: 'Pipeline',
    description:
      '先生成完整剧本，再拆段、补关键帧、串联视频，让长链路创作过程保持可编辑、可恢复、可审核。',
  },
  {
    title: '最小模式也能直接启动',
    icon: <DatabaseOutlined />,
    label: 'Minimal Mode',
    description:
      '本地体验优先走 SQLite + minimal 模式，不需要先搭 MySQL、Redis 或 Celery worker 才能进入主链路。',
  },
]

const publicWorkflowSteps = [
  '角色 / 场景档案入库',
  '生成完整剧本并审核',
  '拆分片段与连续性校正',
  '关键帧生成与首尾串联',
  '分段渲染与最终成片输出',
]

const runtimeCards = [
  {
    title: '最短成功路径',
    badge: 'Local First',
    description: '适合演示、本地试跑和功能验证，重点是尽快进入主链路。',
    items: ['SQLite', 'minimal 模式', '无需 MySQL / Redis / Celery', '调用豆包能力时需要 FFmpeg 与 DOUBAO_API_KEY'],
  },
  {
    title: '完整队列模式',
    badge: 'Queued Runtime',
    description: '适合需要独立 worker、任务排队和更稳定长任务调度的部署场景。',
    items: ['MySQL', 'Redis', 'Celery worker', 'PIPELINE_RUNTIME_MODE=full'],
  },
]

const loggedInFeatureCards = [
  {
    title: '剧本与分镜',
    description: '根据创意描述生成完整剧本，拆分片段并整理镜头重点。',
  },
  {
    title: '角色与场景',
    description: '在角色档案和场景资料中沉淀稳定设定，便于整条视频保持一致。',
  },
  {
    title: '声音与成片',
    description: '视频阶段沿用模型原生音频能力，重点保证画面、节奏与最终成片交付体验。',
  },
]

export const HomePage: React.FC = () => {
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)

  const scrollToCapabilities = () => {
    document.getElementById('landing-capabilities')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (!token) {
    return (
      <div className="landing-shell">
        <section className="landing-hero landing-reveal">
          <div className="landing-grid">
            <div>
              <Tag className="landing-tag">AI Video Workbench</Tag>
              <Title level={1} className="landing-title">
                把零散的
                <br />
                AI 视频生成步骤
                <br />
                组织成一条可控工作流
              </Title>
              <Paragraph className="landing-lead">
                future of video 面向长链路创作，把角色档案、场景档案、剧本生成、片段拆分、关键帧生成和分段渲染串到一个可以反复编辑、继续推进和回看结果的系统里。
              </Paragraph>
              <Space size="middle" wrap className="landing-actions">
                <Button type="primary" size="large" onClick={() => navigate('/login')}>
                  登录开始使用
                </Button>
                <Button size="large" icon={<ArrowRightOutlined />} onClick={scrollToCapabilities}>
                  查看能力边界
                </Button>
              </Space>

            </div>

            <div className="landing-preview-card">
              <div className="landing-preview-header">
                <div>
                  <Text className="landing-preview-label">Core Pipeline</Text>
                  <Title level={3} className="landing-preview-title">
                    从创意描述到最终成片
                  </Title>
                </div>
                <Tag color="gold">Minimal Ready</Tag>
              </div>

              <div className="landing-preview-list">
                {publicWorkflowSteps.map((step, index) => (
                  <div key={step} className="landing-preview-step">
                    <div className="landing-preview-step-index">{index + 1}</div>
                    <div>
                      <div className="landing-preview-step-title">{step}</div>

                    </div>
                  </div>
                ))}
              </div>


            </div>
          </div>
        </section>

        <section className="landing-section landing-reveal landing-reveal-delay-1">
          <div className="landing-metrics">
            <div className="landing-metric">
              <div className="landing-metric-value">Profile-Based</div>
              <div className="landing-metric-label">角色和场景先沉淀，再驱动剧本与镜头</div>
            </div>
            <div className="landing-metric">
              <div className="landing-metric-value">Segmented</div>
              <div className="landing-metric-label">分段生成、逐段确认、支持恢复与重试</div>
            </div>
            <div className="landing-metric">
              <div className="landing-metric-value">Minimal / Full</div>
              <div className="landing-metric-label">同一套主链路兼容本地最小模式和队列部署</div>
            </div>
          </div>
        </section>

        <section id="landing-capabilities" className="landing-section landing-reveal landing-reveal-delay-2">
          <div className="landing-section-head">
            <div>
              <Text className="landing-section-kicker">Capabilities</Text>
              <Title level={2} className="landing-section-title">
                不只是一个调用模型的表单页
              </Title>
            </div>
            <Paragraph className="landing-section-copy">
              这套系统重点解决的是 AI 视频创作里最麻烦的长链路问题：设定难复用、片段难串联、连续性容易丢、生成过程难以恢复。
            </Paragraph>
          </div>

          <Row gutter={[20, 20]}>
            {publicFeatureCards.map((item, index) => (
              <Col xs={24} md={8} key={item.title}>
                <Card className={`landing-feature-card landing-feature-card-${index + 1}`} bordered={false}>
                  <Space direction="vertical" size={14}>
                    <div className="landing-feature-icon">{item.icon}</div>
                    <Tag className="landing-feature-tag">{item.label}</Tag>
                    <Title level={4} className="landing-feature-title">
                      {item.title}
                    </Title>
                    <Paragraph className="landing-feature-copy">{item.description}</Paragraph>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </section>

        <section className="landing-section landing-reveal landing-reveal-delay-3">
          <Row gutter={[20, 20]}>
            {runtimeCards.map((item) => (
              <Col xs={24} md={12} key={item.title}>
                <Card className="landing-runtime-card" bordered={false}>
                  <Space direction="vertical" size={14} style={{ width: '100%' }}>
                    <Tag className="landing-feature-tag">{item.badge}</Tag>
                    <Title level={3} className="landing-runtime-title">
                      {item.title}
                    </Title>
                    <Paragraph className="landing-runtime-copy">{item.description}</Paragraph>
                    <div className="landing-bullet-list">
                      {item.items.map((bullet) => (
                        <div className="landing-bullet-item" key={bullet}>
                          <SafetyCertificateOutlined />
                          <span>{bullet}</span>
                        </div>
                      ))}
                    </div>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </section>
      </div>
    )
  }

  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <Title level={2}>视频创作中心</Title>
        <Paragraph type="secondary" style={{ fontSize: 16, maxWidth: 680, margin: '0 auto' }}>
          从创意描述到最终成片，在同一个项目里完成剧本生成、分段确认、关键帧制作、视频渲染与成片输出。
        </Paragraph>
        <Space size="large" style={{ marginTop: 24 }} wrap>
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
            onClick={() => navigate('/characters/subjects')}
          >
            角色资产台
          </Button>
          <Button
            size="large"
            icon={<PlayCircleOutlined />}
            onClick={() => navigate('/scenes/library')}
          >
            场景档案库
          </Button>
        </Space>
      </div>

      <Row gutter={24} style={{ marginBottom: 48 }}>
        {loggedInFeatureCards.map((item) => (
          <Col xs={24} sm={8} key={item.title}>
            <Card>
              <Space direction="vertical" size={8}>
                <Title level={4} style={{ margin: 0 }}>
                  {item.title}
                </Title>
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {item.description}
                </Paragraph>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="开始方式">
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          新建项目后可以从头完成整条创作流程；如果已经有项目，直接进入项目列表继续编辑即可。
        </Paragraph>
      </Card>
    </div>
  )
}
