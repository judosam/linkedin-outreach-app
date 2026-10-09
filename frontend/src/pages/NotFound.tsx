import { Link, useLocation } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { Button, Card } from '@/components/ui';

export default function NotFound() {
  const { pathname } = useLocation();
  return (
    <div className="mx-auto max-w-[560px] py-8">
      <Card className="p-7">
        <span className="flex h-11 w-11 items-center justify-center rounded-[12px] bg-primary-tint text-primary">
          <Compass size={22} aria-hidden />
        </span>
        <h1 className="mt-4 text-[22px]">Page not found</h1>
        <p className="mt-1.5 text-[14px] text-ink2">
          Nothing is routed at <span className="num">{pathname}</span>.
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Link to="/dashboard">
            <Button variant="primary" isStatic>
              Go to dashboard
            </Button>
          </Link>
          <a href="/legacy">
            <Button variant="secondary" isStatic>
              Open the classic interface
            </Button>
          </a>
        </div>
      </Card>
    </div>
  );
}
