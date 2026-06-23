import { Module } from '@nestjs/common';
import { SsaModule } from '../ssa/ssa.module';
import { CoreService } from './core.service';
import { CoreController } from './core.controller';

@Module({
  imports: [SsaModule],
  controllers: [CoreController],
  providers: [CoreService],
  exports: [CoreService],
})
export class CoreModule {}
