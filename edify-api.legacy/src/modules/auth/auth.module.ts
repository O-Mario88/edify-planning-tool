import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { JwtModule } from '@nestjs/jwt';
import { PassportModule } from '@nestjs/passport';
import { AuthService } from './auth.service';
import { AuthTokensService } from './auth-tokens.service';
import { AuthController } from './auth.controller';
import { JwtStrategy } from '../../common/auth/jwt.strategy';

@Module({
  imports: [
    PassportModule,
    JwtModule.registerAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        secret: config.get<string>('JWT_SECRET'),
        // Short-lived access token — refresh tokens (7d) handle re-auth, so a
        // stolen access token is only useful for ~15 minutes.
        signOptions: { expiresIn: config.get<string>('ACCESS_TOKEN_TTL') ?? '15m' },
      }),
    }),
  ],
  controllers: [AuthController],
  providers: [AuthService, AuthTokensService, JwtStrategy],
})
export class AuthModule {}
